// Write every function of the program as a tab separated line:
// entry address, body size in bytes, qualified name, prototype.
//
// Arguments: <output file>
//@category PlustekRE

import java.io.File;
import java.io.PrintWriter;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;

public class DumpFunctionTable extends GhidraScript {

    @Override
    public void run() throws Exception {
        File outputFile = new File(getScriptArgs()[0]);
        outputFile.getParentFile().mkdirs();
        try (PrintWriter writer = new PrintWriter(outputFile)) {
            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            for (Function function : functions) {
                writer.println(function.getEntryPoint() + "\t"
                    + function.getBody().getNumAddresses() + "\t"
                    + function.getName(true) + "\t"
                    + function.getSignature().getPrototypeString());
            }
        }
    }
}
