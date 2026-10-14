// For every function, write one tab separated line per reference to its entry
// point: callee entry, callee name, reference type (for example
// UNCONDITIONAL_CALL, DATA), referencing address, and the function that
// contains the referencing address ("-" for data outside any function, such as
// vtables and function tables). This is the call graph plus the pointer uses,
// for a binary without symbols where callers must be traced by address.
//
// Arguments: <output file>
//@category PlustekRE

import java.io.File;
import java.io.PrintWriter;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;

public class DumpReferencesToFunctions extends GhidraScript {

    private String containingFunctionText(Reference reference) {
        Function function = getFunctionContaining(reference.getFromAddress());
        return function == null ? "-" : function.getEntryPoint() + "\t" + function.getName(true);
    }

    @Override
    public void run() throws Exception {
        File outputFile = new File(getScriptArgs()[0]);
        try (PrintWriter writer = new PrintWriter(outputFile)) {
            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            for (Function callee : functions) {
                for (Reference reference : getReferencesTo(callee.getEntryPoint())) {
                    writer.println(callee.getEntryPoint() + "\t" + callee.getName(true) + "\t"
                        + reference.getReferenceType() + "\t" + reference.getFromAddress() + "\t"
                        + containingFunctionText(reference));
                }
            }
        }
    }
}
