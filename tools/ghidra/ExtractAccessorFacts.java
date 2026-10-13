// Dump the raw facts that define each register field accessor of the given
// ASIC classes (for example CGL128), as one JSON object per line:
//   - the demangled signature (getter "(bool, int)" or setter "(int, bool, int)")
//   - every call with its constant arguments (CRegister::SetRegs, GetRegs,
//     CIOUSB::ReadRegs, WriteRegs, ...)
//   - every constant used by AND, OR, shift and compare operations
//   - every constant offset used to form a LOAD or STORE address
//   - constant return values (stub accessors that do nothing on this chip)
// The facts come from the decompiler's P-code, so small constants are seen as
// numbers even where the C output prints them as Mach-O header symbols.
// tools/ghidra/register_fields.py turns these facts into a field table.
//
// Arguments: <output file> <class>[,<class>...]
//@category PlustekRE

import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Set;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.pcode.HighFunction;
import ghidra.program.model.pcode.PcodeOp;
import ghidra.program.model.pcode.PcodeOpAST;
import ghidra.program.model.pcode.Varnode;

public class ExtractAccessorFacts extends GhidraScript {

    private static String quote(String text) {
        return "\"" + text.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ") + "\"";
    }

    private static String hex(long value) {
        return quote(String.format("0x%x", value));
    }

    private String calleeName(PcodeOp op) {
        Address target = op.getInput(0).getAddress();
        Function callee = getFunctionAt(target);
        return callee == null ? target.toString() : callee.getName(true);
    }

    // Fold a varnode to a constant when it is built from constants only, as
    // the decompiler does for small numbers it prints as Mach-O header
    // fields (PTRSUB of constant 0 and a constant offset, casts, copies).
    private static Long resolveConstant(Varnode varnode, int depth) {
        if (varnode == null || depth > 8) {
            return null;
        }
        if (varnode.isConstant()) {
            return varnode.getOffset();
        }
        PcodeOp definition = varnode.getDef();
        if (definition == null) {
            return null;
        }
        switch (definition.getOpcode()) {
            case PcodeOp.COPY:
            case PcodeOp.CAST:
            case PcodeOp.INT_ZEXT:
            case PcodeOp.INT_SEXT:
            case PcodeOp.SUBPIECE:
                return resolveConstant(definition.getInput(0), depth + 1);
            case PcodeOp.INT_ADD:
            case PcodeOp.PTRSUB: {
                Long left = resolveConstant(definition.getInput(0), depth + 1);
                Long right = resolveConstant(definition.getInput(1), depth + 1);
                return left == null || right == null ? null : left + right;
            }
            case PcodeOp.PTRADD: {
                Long base = resolveConstant(definition.getInput(0), depth + 1);
                Long index = resolveConstant(definition.getInput(1), depth + 1);
                Long size = resolveConstant(definition.getInput(2), depth + 1);
                return base == null || index == null || size == null ? null : base + index * size;
            }
            default:
                return null;
        }
    }

    private static List<String> constantInputs(PcodeOp op, int firstInput) {
        List<String> values = new ArrayList<>();
        for (int index = firstInput; index < op.getNumInputs(); index++) {
            Long value = resolveConstant(op.getInput(index), 0);
            values.add(value != null ? hex(value) : "null");
        }
        return values;
    }

    private static Varnode skipCasts(Varnode varnode) {
        Varnode current = varnode;
        for (int depth = 0; depth < 8 && current.getDef() != null; depth++) {
            int opcode = current.getDef().getOpcode();
            if (opcode != PcodeOp.CAST && opcode != PcodeOp.COPY) {
                break;
            }
            current = current.getDef().getInput(0);
        }
        return current;
    }

    private static Long constantOffsetOfAddress(Varnode address) {
        PcodeOp definition = skipCasts(address).getDef();
        if (definition == null) {
            return null;
        }
        int opcode = definition.getOpcode();
        if (opcode == PcodeOp.INT_ADD || opcode == PcodeOp.PTRSUB) {
            return resolveConstant(definition.getInput(1), 0);
        }
        if (opcode == PcodeOp.PTRADD) {
            Long index = resolveConstant(definition.getInput(1), 0);
            Long elementSize = resolveConstant(definition.getInput(2), 0);
            if (index != null && elementSize != null) {
                return index * elementSize;
            }
        }
        return null;
    }

    private String plateComment(Function function) {
        String comment = currentProgram.getListing().getComment(CodeUnit.PLATE_COMMENT,
            function.getEntryPoint());
        return comment == null ? "" : comment.trim();
    }

    private String factsOf(Function function, HighFunction high) {
        List<String> calls = new ArrayList<>();
        List<String> ands = new ArrayList<>();
        List<String> ors = new ArrayList<>();
        List<String> rightShifts = new ArrayList<>();
        List<String> leftShifts = new ArrayList<>();
        List<String> memoryOffsets = new ArrayList<>();
        List<String> returns = new ArrayList<>();
        Iterator<PcodeOpAST> ops = high.getPcodeOps();
        while (ops.hasNext()) {
            PcodeOpAST op = ops.next();
            int opcode = op.getOpcode();
            if (opcode == PcodeOp.CALL) {
                calls.add("{\"callee\":" + quote(calleeName(op)) + ",\"arguments\":"
                    + constantInputs(op, 1) + "}");
            }
            else if (opcode == PcodeOp.INT_AND || opcode == PcodeOp.INT_OR
                || opcode == PcodeOp.INT_RIGHT || opcode == PcodeOp.INT_SRIGHT
                || opcode == PcodeOp.INT_LEFT) {
                Varnode right = op.getInput(1);
                if (!right.isConstant()) {
                    continue;
                }
                String value = hex(right.getOffset());
                if (opcode == PcodeOp.INT_AND) {
                    ands.add(value);
                }
                else if (opcode == PcodeOp.INT_OR) {
                    ors.add(value);
                }
                else if (opcode == PcodeOp.INT_LEFT) {
                    leftShifts.add(value);
                }
                else {
                    rightShifts.add(value);
                }
            }
            else if (opcode == PcodeOp.LOAD || opcode == PcodeOp.STORE) {
                Long offset = constantOffsetOfAddress(op.getInput(1));
                if (offset != null) {
                    String kind = opcode == PcodeOp.LOAD ? "load" : "store";
                    memoryOffsets.add("{\"kind\":\"" + kind + "\",\"offset\":" + hex(offset)
                        + ",\"size\":" + (opcode == PcodeOp.LOAD
                            ? op.getOutput().getSize() : op.getInput(2).getSize()) + "}");
                }
            }
            else if (opcode == PcodeOp.RETURN && op.getNumInputs() > 1) {
                Long value = resolveConstant(op.getInput(1), 0);
                if (value != null) {
                    returns.add(hex(value));
                }
            }
        }
        return "{\"class\":" + quote(function.getParentNamespace().getName())
            + ",\"name\":" + quote(function.getName())
            + ",\"address\":" + quote(function.getEntryPoint().toString())
            + ",\"signature\":" + quote(plateComment(function))
            + ",\"calls\":" + calls
            + ",\"and\":" + ands
            + ",\"or\":" + ors
            + ",\"shift_right\":" + rightShifts
            + ",\"shift_left\":" + leftShifts
            + ",\"memory\":" + memoryOffsets
            + ",\"returns\":" + returns + "}";
    }

    @Override
    public void run() throws Exception {
        String[] arguments = getScriptArgs();
        File outputFile = new File(arguments[0]);
        Set<String> classes = new HashSet<>(Arrays.asList(arguments[1].split(",")));

        DecompInterface decompiler = new DecompInterface();
        decompiler.setOptions(new DecompileOptions());
        decompiler.openProgram(currentProgram);
        try (PrintWriter writer = new PrintWriter(outputFile)) {
            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            for (Function function : functions) {
                if (monitor.isCancelled()) {
                    break;
                }
                if (!classes.contains(function.getParentNamespace().getName())) {
                    continue;
                }
                DecompileResults results = decompiler.decompileFunction(function, 120, monitor);
                HighFunction high = results.getHighFunction();
                if (high == null) {
                    writer.println("{\"name\":" + quote(function.getName(true))
                        + ",\"address\":" + quote(function.getEntryPoint().toString())
                        + ",\"error\":" + quote(String.valueOf(results.getErrorMessage())) + "}");
                    continue;
                }
                writer.println(factsOf(function, high));
            }
        }
        decompiler.dispose();
    }
}
