// Decompile every function whose qualified name matches a regular expression
// and write the C output, one file per function, plus an index.
//
// Arguments: <output directory> <java regex on Namespace::name>
// Example:   work/re/decomp/ciousb '^CIOUSB::'
//@category PlustekRE

import java.io.File;
import java.io.PrintWriter;
import java.util.regex.Pattern;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;

public class DecompileMatching extends GhidraScript {

    private static String fileNameFor(Function function) {
        String name = function.getName(true).replaceAll("[^A-Za-z0-9_.~-]", "_");
        return name + "@" + function.getEntryPoint().toString() + ".c";
    }

    @Override
    public void run() throws Exception {
        String[] arguments = getScriptArgs();
        File outputDirectory = new File(arguments[0]);
        Pattern pattern = Pattern.compile(arguments[1]);
        outputDirectory.mkdirs();

        DecompInterface decompiler = new DecompInterface();
        decompiler.setOptions(new DecompileOptions());
        decompiler.openProgram(currentProgram);

        try (PrintWriter index = new PrintWriter(new File(outputDirectory, "INDEX.tsv"))) {
            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            for (Function function : functions) {
                if (monitor.isCancelled()) {
                    break;
                }
                String qualifiedName = function.getName(true);
                if (!pattern.matcher(qualifiedName).find()) {
                    continue;
                }
                DecompileResults results = decompiler.decompileFunction(function, 120, monitor);
                String body = results.decompileCompleted()
                    ? results.getDecompiledFunction().getC()
                    : "// decompilation failed: " + results.getErrorMessage() + "\n";
                String fileName = fileNameFor(function);
                try (PrintWriter writer = new PrintWriter(new File(outputDirectory, fileName))) {
                    writer.println("// " + qualifiedName + " at " + function.getEntryPoint());
                    writer.println("// signature: " + function.getSignature().getPrototypeString());
                    writer.print(body);
                }
                index.println(function.getEntryPoint() + "\t" + qualifiedName + "\t" + fileName);
            }
        }
        decompiler.dispose();
    }
}
