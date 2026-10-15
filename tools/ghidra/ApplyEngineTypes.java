// Make the decompiler output of the macOS engine read like the source:
// member functions get __thiscall with a typed "this", the demangled
// parameter types and a return type, the Mach-O header block at address 0
// goes away so that small constants stop printing as header fields, and the
// classes get structures with the members the code reveals.
//
// Arguments: <classes.tsv> <vtables.tsv>, both from macho_engine_tables.py
// Run on a fresh import (the script changes the program), see README.md.
//@category PlustekRE

import java.io.BufferedReader;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.BitSet;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.app.util.NamespaceUtils;
import ghidra.app.util.demangler.DemangledFunction;
import ghidra.app.util.demangler.DemangledObject;
import ghidra.app.util.demangler.DemangledParameter;
import ghidra.app.util.demangler.DemanglerUtil;
import ghidra.program.model.data.AbstractFloatDataType;
import ghidra.program.model.data.ArrayDataType;
import ghidra.program.model.data.BooleanDataType;
import ghidra.program.model.data.CategoryPath;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataTypeConflictHandler;
import ghidra.program.model.data.DataTypeManager;
import ghidra.program.model.data.EnumDataType;
import ghidra.program.model.data.IntegerDataType;
import ghidra.program.model.data.LongDataType;
import ghidra.program.model.data.PointerTypedefBuilder;
import ghidra.program.model.data.PointerDataType;
import ghidra.program.model.data.SignedCharDataType;
import ghidra.program.model.data.Structure;
import ghidra.program.model.data.StructureDataType;
import ghidra.program.model.data.TypeDef;
import ghidra.program.model.data.Undefined;
import ghidra.program.model.data.UnsignedShortDataType;
import ghidra.program.model.data.VoidDataType;
import ghidra.program.model.data.CharDataType;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Function.FunctionUpdateType;
import ghidra.program.model.listing.GhidraClass;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Parameter;
import ghidra.program.model.listing.ParameterImpl;
import ghidra.program.model.listing.VariableUtilities;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.pcode.HighFunction;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.data.DataUtilities;

public class ApplyEngineTypes extends GhidraScript {

    private static final String[] ARGUMENT_REGISTERS = { "RDI", "RSI", "RDX", "RCX", "R8", "R9" };
    private static final int ENTRY_SCAN_LIMIT = 64;
    private static final int FIRST_STACK_ARGUMENT = 0x10;
    private static final int STACK_SLOT_SIZE = 8;
    private static final Pattern BASE_OBJECT_STRUCTOR =
        Pattern.compile("^_?_ZN(\\d+)([A-Za-z_][A-Za-z0-9_]*?)(C2|D2)E");
    private static final String CATEGORY = "/PlustekEngine";
    private static final Map<String, Integer> PLACEHOLDER_SIZES = Map.of("_SCANAPI_INPUT_SOURCE", 8);
    private static final int PLACEHOLDER_DEFAULT_SIZE = 4;

    private final Map<String, Integer> nonVirtualSizes = new HashMap<>();
    private final Set<String> classesWithVirtualBases = new HashSet<>();
    private final Map<String, TreeMap<Integer, String>> virtualBaseSlots = new HashMap<>();
    private final Map<String, TreeMap<Integer, String>> virtualFunctionSlots = new HashMap<>();
    private final Map<String, Integer> outcomes = new TreeMap<>();

    @Override
    public void run() throws Exception {
        readClassTable(getScriptArgs()[0]);
        readVtableTable(getScriptArgs()[1]);
        removeHeaderBlock();
        defineClassStructures();
        List<Function> functions = new ArrayList<>();
        currentProgram.getFunctionManager().getFunctions(true).forEach(functions::add);
        for (Function function : functions) {
            count(applySignature(function));
        }
        for (Function function : functions) {
            if (returnsBoolAtEveryExit(function)) {
                function.setReturnType(BooleanDataType.dataType, SourceType.ANALYSIS);
                count("return bool");
            }
        }
        commitDecompiledReturnTypes(functions);
        println("ApplyEngineTypes: " + outcomes);
    }

    private void count(String outcome) {
        outcomes.merge(outcome, 1, Integer::sum);
    }

    // ---- class table -------------------------------------------------------

    // The non-virtual size of a class is the distance to the next virtual
    // base in the complete object layouts of the class table. Only gaps that
    // follow a class are known, so the last base of every layout stays open.
    private void readClassTable(String path) throws Exception {
        Map<String, TreeMap<Integer, String>> layouts = new HashMap<>();
        try (BufferedReader reader = new BufferedReader(new FileReader(path))) {
            reader.readLine();
            for (String line = reader.readLine(); line != null; line = reader.readLine()) {
                String[] columns = line.split("\t", -1);
                virtualBaseSlots.computeIfAbsent(columns[0], key -> new TreeMap<>());
                if (columns[2].contains("virtual base") && !columns[4].isEmpty()) {
                    classesWithVirtualBases.add(columns[0]);
                    virtualBaseSlots.get(columns[0]).put(-Integer.parseInt(columns[3].substring(3), 16), columns[1]);
                    layouts.computeIfAbsent(columns[0], key -> new TreeMap<>())
                        .put(Integer.parseInt(columns[4]), columns[1]);
                }
            }
        }
        for (Map.Entry<String, TreeMap<Integer, String>> layout : layouts.entrySet()) {
            nonVirtualSizes.putIfAbsent(layout.getKey(), layout.getValue().firstKey());
            Integer previousOffset = null;
            String previousClass = null;
            for (Map.Entry<Integer, String> base : layout.getValue().entrySet()) {
                if (previousClass != null) {
                    nonVirtualSizes.putIfAbsent(previousClass, base.getKey() - previousOffset);
                }
                previousOffset = base.getKey();
                previousClass = base.getValue();
            }
        }
    }

    private void readVtableTable(String path) throws Exception {
        try (BufferedReader reader = new BufferedReader(new FileReader(path))) {
            reader.readLine();
            for (String line = reader.readLine(); line != null; line = reader.readLine()) {
                String[] columns = line.split("\t", -1);
                virtualFunctionSlots.computeIfAbsent(columns[0], key -> new TreeMap<>())
                    .put(Integer.parseInt(columns[1].substring(2), 16), slotName(columns[3], columns[1]));
            }
        }
    }

    // Field name for a vtable entry: the method name, "destructor" for D1,
    // "deletingDestructor" for D0, "pureVirtual<slot>" for ___cxa_pure_virtual.
    private static String slotName(String symbol, String slot) {
        if (symbol.endsWith("D1Ev")) {
            return "destructor";
        }
        if (symbol.endsWith("D0Ev")) {
            return "deletingDestructor";
        }
        if (symbol.startsWith("__ZN")) {
            String afterClass = skipLengthPrefixedName(symbol.substring(4));
            int methodLength = leadingNumber(afterClass);
            if (methodLength > 0) {
                return skipDigits(afterClass).substring(0, methodLength);
            }
        }
        return "pureVirtual" + slot.substring(2);
    }

    private static String skipDigits(String text) {
        int end = 0;
        while (end < text.length() && Character.isDigit(text.charAt(end))) {
            end++;
        }
        return text.substring(end);
    }

    private static String skipLengthPrefixedName(String text) {
        return skipDigits(text).substring(leadingNumber(text));
    }

    private static int leadingNumber(String text) {
        int digits = text.length() - skipDigits(text).length();
        return digits == 0 ? 0 : Integer.parseInt(text.substring(0, digits));
    }

    // ---- (b) the Mach-O header ---------------------------------------------

    // The loader maps the Mach-O header and load commands as a block at
    // address 0. Nothing executes or is referenced there, but the decompiler
    // prints every small constant that it takes for a pointer as a field of
    // that header ("(long)&MACH_HEADER.magic + 2" for 2).
    private void removeHeaderBlock() throws Exception {
        MemoryBlock block = currentProgram.getMemory().getBlock(toAddr(0));
        if (block != null && !block.isOverlay() && block.getName().equals("__TEXT")) {
            currentProgram.getMemory().removeBlock(block, monitor);
            println("ApplyEngineTypes: removed block " + block.getName() + " " + block.getStart() + "-" + block.getEnd());
        }
    }

    // ---- (c) class structures ----------------------------------------------

    private void defineClassStructures() throws Exception {
        DataTypeManager manager = currentProgram.getDataTypeManager();
        DataType unsignedShort = UnsignedShortDataType.dataType;

        Structure registerLink = new StructureDataType(new CategoryPath(CATEGORY), "RegisterLink", 0, manager);
        registerLink.add(unsignedShort, "previous", "reconstructed: register linked before this one, 0xffff for none");
        registerLink.add(unsignedShort, "next", "reconstructed: register linked after this one, 0xffff for none");
        DataType link = manager.addDataType(registerLink, DataTypeConflictHandler.REPLACE_HANDLER);

        Structure register = classStructure("CRegister");
        placeVirtualTablePointer(register, "CRegister");
        place(register, 0x8, new ArrayDataType(unsignedShort, 0x120, 2), "m_reg",
            "named after CRegister::Dump_m_reg_ToConsole; GetRegBuf() returns it, cleared over 0x240 bytes by the constructor");
        place(register, 0x248, unsignedShort, "registerLinkFirst", "reconstructed: first register of the list SetLink builds");
        place(register, 0x24a, unsignedShort, "registerLinkLast", "reconstructed: last register of that list");
        place(register, 0x24c, new ArrayDataType(link, 0x120, 4), "registerLinks", "reconstructed: SetLink(register, ..., 0)");
        place(register, 0x6cc, new ArrayDataType(unsignedShort, 0x30, 2), "afeRegisters",
            "reconstructed: GetAfeBuf() returns it, cleared over 0x60 bytes by the constructor");
        place(register, 0x72c, unsignedShort, "afeLinkFirst", "reconstructed: first AFE register of the list SetLink builds");
        place(register, 0x72e, unsignedShort, "afeLinkLast", "reconstructed: last AFE register of that list");
        place(register, 0x730, new ArrayDataType(link, 0x30, 4), "afeLinks", "reconstructed: SetLink(register, ..., 1)");

        for (String chip : new String[] { "CGL125", "CGL126", "CGL128", "CGL846" }) {
            Structure accessor = classStructure(chip);
            placeVirtualTablePointer(accessor, chip);
            DataType registers = new PointerDataType(unsignedShort);
            place(accessor, 0x8, registers, "regBuf",
                "reconstructed: CRegister::GetRegBuf() of the CRegister base, set by the constructor; WriteRegs sends from here");
            place(accessor, 0x10, registers, "regShadow",
                "reconstructed: set to regBuf by the constructor; the field setters change bits here");
        }

        Structure registry = classStructure("CRegistry");
        placeVirtualTablePointer(registry, "CRegistry");
        place(registry, 0xf5d0, new PointerDataType(IntegerDataType.dataType), "propertyValues",
            "reconstructed: new int[m_PropSize] in the constructor; m_prop[key].index selects the value");
        typeRegistryPropertyTable(manager);

        for (String className : virtualBaseSlots.keySet()) {
            Structure structure = classStructure(className);
            if (structure.getNumDefinedComponents() == 0) {
                placeVirtualTablePointer(structure, className);
            }
        }
    }

    // The vptr points past the virtual base offsets, the offset to top and
    // the type information pointer of the class's vtable. An offset pointer
    // (Ghidra prints ADJ(vptr)->field) lets those slots carry names, so that
    // "this + vptr[-0x28]" reads as the CRegistry offset in CAsic.
    private void placeVirtualTablePointer(Structure structure, String className) throws Exception {
        DataTypeManager manager = currentProgram.getDataTypeManager();
        Structure vtable = new StructureDataType(new CategoryPath(CATEGORY), className + "_vtable", 0, manager);
        TreeMap<Integer, String> bases = virtualBaseSlots.getOrDefault(className, new TreeMap<>());
        for (Map.Entry<Integer, String> base : bases.entrySet()) {
            vtable.add(LongDataType.dataType, 8, base.getValue() + "Offset",
                "offset of the virtual base " + base.getValue() + ", vtable slot -0x" + Integer.toHexString(-base.getKey()));
        }
        vtable.add(LongDataType.dataType, 8, "offsetToTop", null);
        vtable.add(PointerDataType.dataType, 8, "typeinfo", null);
        int addressPoint = vtable.getLength();
        for (Map.Entry<Integer, String> function : virtualFunctionSlots.getOrDefault(className, new TreeMap<>()).entrySet()) {
            vtable.add(PointerDataType.dataType, 8, function.getValue(), "slot 0x" + Integer.toHexString(function.getKey()));
        }
        DataType resolved = manager.addDataType(vtable, DataTypeConflictHandler.REPLACE_HANDLER);
        DataType pointer = new PointerTypedefBuilder(resolved, 8, manager)
            .componentOffset(addressPoint)
            .name(className + "_vptr")
            .build();
        pointer = manager.addDataType(pointer, DataTypeConflictHandler.REPLACE_HANDLER);
        place(structure, 0x0, pointer, "vptr", "reconstructed name; points into " + className + "_vtable");
    }

    private Structure classStructure(String className) throws Exception {
        Namespace namespace = getNamespace(null, className);
        if (namespace == null) {
            namespace = currentProgram.getSymbolTable().createNameSpace(null, className, SourceType.ANALYSIS);
        }
        GhidraClass ghidraClass = namespace instanceof GhidraClass
            ? (GhidraClass) namespace
            : NamespaceUtils.convertNamespaceToClass(namespace);
        Structure structure = VariableUtilities.findOrCreateClassStruct(ghidraClass, currentProgram.getDataTypeManager());
        Integer size = nonVirtualSizes.get(className);
        if (size != null && structure.getLength() < size) {
            structure.growStructure(size - structure.getLength());
        }
        return structure;
    }

    private void place(Structure structure, int offset, DataType type, String name, String comment) {
        int end = offset + type.getLength();
        if (structure.getLength() < end) {
            structure.growStructure(end - structure.getLength());
        }
        structure.replaceAtOffset(offset, type, type.getLength(), name, comment);
    }

    // CRegistry::m_prop: 16 byte entries {key string, value count, value index}.
    private void typeRegistryPropertyTable(DataTypeManager manager) throws Exception {
        Symbol table = null;
        for (Symbol symbol : currentProgram.getSymbolTable().getSymbols("m_prop", getNamespace(null, "CRegistry"))) {
            table = symbol;
        }
        if (table == null) {
            println("ApplyEngineTypes: CRegistry::m_prop not found");
            return;
        }
        Structure entry = new StructureDataType(new CategoryPath(CATEGORY), "RegistryProperty", 0, manager);
        entry.add(new PointerDataType(CharDataType.dataType), "key", "reconstructed: plist key, also the accessor's name");
        entry.add(IntegerDataType.dataType, "valueCount", "reconstructed: number of comma separated values");
        entry.add(IntegerDataType.dataType, "index", "reconstructed: first value in propertyValues, set at run time");
        DataType entryType = manager.addDataType(entry, DataTypeConflictHandler.REPLACE_HANDLER);
        Address start = table.getAddress();
        int count = 0;
        while (pointsIntoStrings(start.add((long) count * entryType.getLength()))) {
            count++;
        }
        DataUtilities.createData(currentProgram, start, new ArrayDataType(entryType, count, entryType.getLength()),
            -1, DataUtilities.ClearDataMode.CLEAR_ALL_CONFLICT_DATA);
        println("ApplyEngineTypes: typed CRegistry::m_prop as " + count + " entries");
    }

    private boolean pointsIntoStrings(Address entry) throws Exception {
        MemoryBlock block = currentProgram.getMemory().getBlock(toAddr(getLong(entry)));
        return block != null && block.getName().equals("__cstring");
    }

    // ---- (a) signatures ------------------------------------------------------

    private String mangledName(Function function) {
        for (Symbol symbol : currentProgram.getSymbolTable().getSymbols(function.getEntryPoint())) {
            if (symbol.getName().startsWith("__Z")) {
                return symbol.getName();
            }
        }
        return null;
    }

    private String applySignature(Function function) throws Exception {
        if (function.isExternal() || function.isThunk()) {
            return "skipped: external or thunk";
        }
        String mangled = mangledName(function);
        if (mangled == null) {
            return "skipped: no mangled symbol";
        }
        DemangledObject demangled = demangle(mangled, function.getEntryPoint());
        if (!(demangled instanceof DemangledFunction)) {
            return "skipped: not a plain function (" + (demangled == null ? "no demangling" : demangled.getClass().getSimpleName()) + ")";
        }
        return applyDemangledSignature(function, mangled, (DemangledFunction) demangled);
    }

    private String applyDemangledSignature(Function function, String mangled, DemangledFunction demangled) throws Exception {
        List<DataType> parameterTypes = parameterTypes(demangled);
        String className = enclosingClass(function);
        boolean structor = isStructor(function, className);
        boolean baseObjectStructor = structor && isBaseObjectStructor(mangled, className);
        if (baseObjectStructor) {
            parameterTypes.add(0, new PointerDataType(PointerDataType.dataType));
        }
        int integerParameters = integerParameterCount(parameterTypes);
        if (integerParameters < 0) {
            return "skipped: aggregate passed by value";
        }
        Boolean member = isMember(function, className, structor, integerParameters);
        if (member == null) {
            return "skipped: cannot tell member from static";
        }
        updatePrototype(function, member, parameterTypes, baseObjectStructor, hasVariableArguments(demangled));
        if (structor) {
            function.setReturnType(VoidDataType.dataType, SourceType.IMPORTED);
        }
        if (!member && className != null) {
            println("ApplyEngineTypes: static member " + function.getName(true) + " at " + function.getEntryPoint());
        }
        return member ? "member" : (className == null ? "free function" : "static member");
    }

    private List<DataType> parameterTypes(DemangledFunction demangled) throws Exception {
        List<DataType> types = new ArrayList<>();
        for (DemangledParameter parameter : demangled.getParameters()) {
            if (parameter.getType().isVarArgs()) {
                continue;
            }
            DataType dataType = parameter.getType().getDataType(currentProgram.getDataTypeManager());
            if (dataType != null && !(dataType instanceof VoidDataType)) {
                types.add(concreteType(dataType));
            }
        }
        return types;
    }

    private static boolean hasVariableArguments(DemangledFunction demangled) {
        for (DemangledParameter parameter : demangled.getParameters()) {
            if (parameter.getType().isVarArgs()) {
                return true;
            }
        }
        return false;
    }

    // The demangler turns a type name it does not know (the engine's own
    // types, such as _SCANAPI_INPUT_SOURCE) into a typedef of one undefined
    // byte, and "signed char" into a typedef named "signed". Such a parameter
    // gets no storage, so the decompiler ignores the whole prototype. The
    // types become empty enums of the same name, as wide as the store that
    // spills them at entry: 8 bytes for _SCANAPI_INPUT_SOURCE in all 14
    // functions that take one (MOV qword ptr [RBP + -0x8],RDI in
    // apiLampControl at 0x2f680, which logs only its low 4 bytes), 4 bytes
    // for every other one. The enum is a stand-in for a type the binary does
    // not define: unlike a typedef of undefined bytes, which the decompiler
    // replaces with the type it infers, it keeps the name in the output.
    // "signed" becomes a signed char.
    private DataType concreteType(DataType type) throws Exception {
        if (!(type instanceof TypeDef) || type.getLength() != 1 || !Undefined.isUndefined(((TypeDef) type).getBaseDataType())) {
            return type;
        }
        count("placeholder type replaced: " + type.getName());
        if (type.getName().equals("signed")) {
            return SignedCharDataType.dataType;
        }
        int size = PLACEHOLDER_SIZES.getOrDefault(type.getName(), PLACEHOLDER_DEFAULT_SIZE);
        DataTypeManager manager = currentProgram.getDataTypeManager();
        EnumDataType replacement = new EnumDataType(new CategoryPath(CATEGORY), type.getName(), size, manager);
        return manager.addDataType(replacement, DataTypeConflictHandler.KEEP_HANDLER);
    }

    private static boolean isStructor(Function function, String className) {
        return className != null && (function.getName().equals(className) || function.getName().equals("~" + className));
    }

    // True for a member, false for a static or free function, null when the
    // argument registers cannot tell (six or more integer parameters) and the
    // body reads no more stack arguments than a static function would have.
    private Boolean isMember(Function function, String className, boolean structor, int integerParameters) {
        if (className == null) {
            return false;
        }
        if (structor) {
            return true;
        }
        int registersRead = integerRegistersReadAtEntry(function);
        if (integerParameters + 1 <= ARGUMENT_REGISTERS.length && registersRead == integerParameters + 1) {
            return true;
        }
        if (integerParameters < ARGUMENT_REGISTERS.length && registersRead == integerParameters) {
            return false;
        }
        if (integerParameters >= ARGUMENT_REGISTERS.length && registersRead == ARGUMENT_REGISTERS.length
                && stackArgumentSlotsRead(function) > integerParameters - ARGUMENT_REGISTERS.length) {
            return true;
        }
        println("ApplyEngineTypes: left as analysed, " + registersRead + " argument registers read, "
            + integerParameters + " integer parameters: " + function.getName(true) + " at " + function.getEntryPoint());
        return null;
    }

    private void updatePrototype(Function function, boolean member, List<DataType> parameterTypes,
            boolean baseObjectStructor, boolean variadic) throws Exception {
        if (member) {
            classStructure(enclosingClass(function));
        }
        List<Parameter> parameters = new ArrayList<>();
        for (int index = 0; index < parameterTypes.size(); index++) {
            String name = baseObjectStructor && index == 0 ? "vtt" : null;
            parameters.add(new ParameterImpl(name, parameterTypes.get(index), currentProgram));
        }
        String convention = member ? "__thiscall" : currentProgram.getCompilerSpec().getDefaultCallingConvention().getName();
        function.updateFunction(convention, null, parameters, FunctionUpdateType.DYNAMIC_STORAGE_FORMAL_PARAMS, true,
            SourceType.IMPORTED);
        function.setVarArgs(variadic);
    }

    // Mach-O symbols carry an extra leading underscore before the "_Z".
    private DemangledObject demangle(String mangled, Address address) {
        String itanium = mangled.startsWith("__Z") ? mangled.substring(1) : mangled;
        try {
            List<DemangledObject> results = DemanglerUtil.demangle(currentProgram, itanium, address);
            return results == null || results.isEmpty() ? null : results.get(0);
        }
        catch (Exception exception) {
            count("demangler error: " + exception.getClass().getSimpleName());
            return null;
        }
    }

    private String enclosingClass(Function function) {
        Namespace namespace = function.getParentNamespace();
        if (namespace == null || namespace.isGlobal()) {
            return null;
        }
        return namespace.getName();
    }

    // C2 and D2 of a class with virtual bases take the VTT as a hidden
    // second argument (Itanium C++ ABI, "Constructors and destructors").
    private boolean isBaseObjectStructor(String mangled, String className) {
        Matcher matcher = BASE_OBJECT_STRUCTOR.matcher(mangled);
        return matcher.find() && matcher.group(2).equals(className) && classesWithVirtualBases.contains(className);
    }

    // Number of parameters passed in integer registers, or -1 when one is an
    // aggregate by value, whose classification this script does not attempt.
    private int integerParameterCount(List<DataType> types) {
        int count = 0;
        for (DataType type : types) {
            DataType base = type instanceof TypeDef ? ((TypeDef) type).getBaseDataType() : type;
            if (base instanceof AbstractFloatDataType) {
                continue;
            }
            if (base instanceof Structure || base.getLength() > 8) {
                return -1;
            }
            count++;
        }
        return count;
    }

    // Stack argument slots the body uses: unoptimised clang code keeps the
    // frame pointer, so the first stack argument is [RBP + 0x10], the
    // second [RBP + 0x18], and so on.
    private int stackArgumentSlotsRead(Function function) {
        int slots = 0;
        for (Instruction instruction : currentProgram.getListing().getInstructions(function.getBody(), true)) {
            for (int operand = 0; operand < instruction.getNumOperands(); operand++) {
                slots = Math.max(slots, stackArgumentSlot(instruction.getOpObjects(operand)));
            }
        }
        return slots;
    }

    // 1 for [RBP + 0x10], 2 for [RBP + 0x18], ..., 0 for any other operand.
    private static int stackArgumentSlot(Object[] objects) {
        if (objects.length != 2 || !(objects[0] instanceof Register) || !(objects[1] instanceof Scalar)
                || !((Register) objects[0]).getName().equals("RBP")) {
            return 0;
        }
        long offset = ((Scalar) objects[1]).getSignedValue();
        return offset < FIRST_STACK_ARGUMENT ? 0 : (int) ((offset - FIRST_STACK_ARGUMENT) / STACK_SLOT_SIZE) + 1;
    }

    // Unoptimised clang code stores every argument register to the stack
    // before the first call or branch, so the number of argument registers
    // read before being written tells whether a hidden "this" comes first.
    private int integerRegistersReadAtEntry(Function function) {
        BitSet read = new BitSet();
        Set<String> written = new HashSet<>();
        Instruction instruction = getInstructionAt(function.getEntryPoint());
        for (int index = 0; instruction != null && index < ENTRY_SCAN_LIMIT; index++) {
            if (instruction.getFlowType().isCall() || instruction.getFlowType().isJump()
                || instruction.getFlowType().isTerminal()) {
                break;
            }
            if (!clearsItsRegister(instruction)) {
                for (Object input : instruction.getInputObjects()) {
                    noteRead(input, written, read);
                }
            }
            for (Object result : instruction.getResultObjects()) {
                if (result instanceof Register) {
                    written.add(((Register) result).getBaseRegister().getName());
                }
            }
            instruction = instruction.getNext();
        }
        return read.length();
    }

    private void noteRead(Object input, Set<String> written, BitSet read) {
        if (!(input instanceof Register)) {
            return;
        }
        String base = ((Register) input).getBaseRegister().getName();
        for (int index = 0; index < ARGUMENT_REGISTERS.length; index++) {
            if (ARGUMENT_REGISTERS[index].equals(base) && !written.contains(base)) {
                read.set(index);
            }
        }
    }

    private boolean clearsItsRegister(Instruction instruction) {
        String mnemonic = instruction.getMnemonicString();
        if (!mnemonic.equals("XOR") && !mnemonic.equals("SUB")) {
            return false;
        }
        Object[] first = instruction.getOpObjects(0);
        Object[] second = instruction.getOpObjects(1);
        return first.length == 1 && second.length == 1 && first[0].equals(second[0]);
    }

    // ---- return types --------------------------------------------------------

    // A bool return at -O0 ends in "AND AL,0x1; MOVZX EAX,AL" before the
    // epilogue (zero extension of the i1 value).
    private boolean returnsBoolAtEveryExit(Function function) {
        if (function.isExternal() || function.isThunk()) {
            return false;
        }
        boolean sawReturn = false;
        for (Instruction instruction : currentProgram.getListing().getInstructions(function.getBody(), true)) {
            if (!instruction.getFlowType().isTerminal() || !instruction.getMnemonicString().equals("RET")) {
                continue;
            }
            sawReturn = true;
            Instruction previous = skipEpilogue(instruction.getPrevious());
            if (previous == null || !previous.toString().equals("MOVZX EAX,AL")) {
                return false;
            }
            Instruction mask = previous.getPrevious();
            if (mask == null || !mask.toString().equals("AND AL,0x1")) {
                return false;
            }
        }
        return sawReturn;
    }

    private Instruction skipEpilogue(Instruction instruction) {
        while (instruction != null && (instruction.getMnemonicString().equals("POP")
            || instruction.toString().startsWith("ADD RSP,"))) {
            instruction = instruction.getPrevious();
        }
        return instruction;
    }

    // The demangled names carry no return types (GNU mangling encodes them
    // only for templates), so the decompiler's own inference is committed
    // for every function whose return type is still undefined, except void:
    // a function that ends by calling another one ("CALL; POP RBP; RET")
    // passes that call's result on unchanged, and while the callee's return
    // type is undefined the decompiler takes the caller for void, which would
    // cut the value off in every caller. Two rounds let such a function pick
    // up the type committed for its callee in the first. One and two byte
    // inferences are left undefined too: the decompiler reads them off a
    // MOVZX of a narrow field, while the callers use all of EAX (an int in
    // the source), so committing them breaks every caller into CONCAT62.
    private static final int RETURN_TYPE_ROUNDS = 2;
    private static final int MINIMUM_COMMITTED_RETURN_SIZE = 4;

    private void commitDecompiledReturnTypes(List<Function> functions) throws Exception {
        DecompInterface decompiler = new DecompInterface();
        decompiler.setOptions(new DecompileOptions());
        decompiler.openProgram(currentProgram);
        try {
            for (int round = 1; round <= RETURN_TYPE_ROUNDS; round++) {
                for (Function function : functions) {
                    if (monitor.isCancelled()) {
                        break;
                    }
                    if (function.isExternal() || function.isThunk() || !Undefined.isUndefined(function.getReturnType())) {
                        continue;
                    }
                    count("return round " + round + ": " + commitDecompiledReturnType(decompiler, function));
                }
            }
        }
        finally {
            decompiler.dispose();
        }
    }

    private String commitDecompiledReturnType(DecompInterface decompiler, Function function) throws Exception {
        DecompileResults results = decompiler.decompileFunction(function, 120, monitor);
        HighFunction high = results.getHighFunction();
        if (high == null) {
            return "decompilation failed";
        }
        DataType returnType = high.getFunctionPrototype().getReturnType();
        if (returnType == null || Undefined.isUndefined(returnType)) {
            return "still undefined";
        }
        if (returnType instanceof VoidDataType) {
            return "void left undefined";
        }
        if (returnType.getLength() < MINIMUM_COMMITTED_RETURN_SIZE) {
            return "narrow type left undefined";
        }
        function.setReturnType(returnType, SourceType.ANALYSIS);
        return "from decompiler";
    }
}
