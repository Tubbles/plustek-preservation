// For every call to a function whose qualified name matches a regular
// expression, write one tab separated line: caller, call site address,
// callee, and the call's arguments (constant values in hex, "?" otherwise).
// Only the callers found through references are decompiled.
//
// Arguments: <output file> <java regex on callee Namespace::name>
// Example:   work/re/control-calls.tsv '^CIOUSB::Control(Read|Write)$'
//@category PlustekRE

import java.io.File;
import java.io.PrintWriter;
import java.util.Iterator;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Pattern;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.pcode.HighFunction;
import ghidra.program.model.pcode.PcodeOp;
import ghidra.program.model.pcode.PcodeOpAST;
import ghidra.program.model.pcode.Varnode;
import ghidra.program.model.symbol.Reference;

public class ListCallsWithConstants extends GhidraScript {

    private Set<Address> callersOf(Pattern pattern) {
        Set<Address> callers = new TreeSet<>();
        FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
        for (Function function : functions) {
            if (!pattern.matcher(function.getName(true)).find()) {
                continue;
            }
            for (Reference reference : getReferencesTo(function.getEntryPoint())) {
                Function caller = getFunctionContaining(reference.getFromAddress());
                if (caller != null) {
                    callers.add(caller.getEntryPoint());
                }
            }
        }
        return callers;
    }

    private static String argumentText(Varnode input) {
        return input.isConstant() ? String.format("0x%x", input.getOffset()) : "?";
    }

    @Override
    public void run() throws Exception {
        String[] arguments = getScriptArgs();
        File outputFile = new File(arguments[0]);
        Pattern pattern = Pattern.compile(arguments[1]);

        DecompInterface decompiler = new DecompInterface();
        decompiler.setOptions(new DecompileOptions());
        decompiler.openProgram(currentProgram);
        try (PrintWriter writer = new PrintWriter(outputFile)) {
            for (Address callerEntry : callersOf(pattern)) {
                Function caller = getFunctionAt(callerEntry);
                DecompileResults results = decompiler.decompileFunction(caller, 120, monitor);
                HighFunction high = results.getHighFunction();
                if (high == null) {
                    writer.println(caller.getName(true) + "\t" + callerEntry + "\t?\tdecompile failed");
                    continue;
                }
                Iterator<PcodeOpAST> ops = high.getPcodeOps();
                while (ops.hasNext()) {
                    PcodeOpAST op = ops.next();
                    if (op.getOpcode() != PcodeOp.CALL) {
                        continue;
                    }
                    Function callee = getFunctionAt(op.getInput(0).getAddress());
                    if (callee == null || !pattern.matcher(callee.getName(true)).find()) {
                        continue;
                    }
                    StringBuilder line = new StringBuilder();
                    line.append(caller.getName(true)).append('\t')
                        .append(op.getSeqnum().getTarget()).append('\t')
                        .append(callee.getName(true));
                    for (int index = 1; index < op.getNumInputs(); index++) {
                        line.append('\t').append(argumentText(op.getInput(index)));
                    }
                    writer.println(line);
                }
            }
        }
        decompiler.dispose();
    }
}
