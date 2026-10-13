// Write the disassembly of every function whose qualified name matches a
// regular expression, one file per function (address, bytes, instruction).
//
// Arguments: <output directory> <java regex on Namespace::name>
//@category PlustekRE

import java.io.File;
import java.io.PrintWriter;
import java.util.regex.Pattern;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;

public class DisassembleMatching extends GhidraScript {

    private static String hexBytes(byte[] bytes) {
        StringBuilder builder = new StringBuilder();
        for (byte value : bytes) {
            builder.append(String.format("%02x", value & 0xff));
        }
        return builder.toString();
    }

    @Override
    public void run() throws Exception {
        String[] arguments = getScriptArgs();
        File outputDirectory = new File(arguments[0]);
        Pattern pattern = Pattern.compile(arguments[1]);
        outputDirectory.mkdirs();
        FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
        for (Function function : functions) {
            String qualifiedName = function.getName(true);
            if (!pattern.matcher(qualifiedName).find()) {
                continue;
            }
            String fileName = qualifiedName.replaceAll("[^A-Za-z0-9_.~-]", "_") + "@"
                + function.getEntryPoint() + ".s";
            try (PrintWriter writer = new PrintWriter(new File(outputDirectory, fileName))) {
                writer.println("; " + qualifiedName + " at " + function.getEntryPoint());
                InstructionIterator instructions =
                    currentProgram.getListing().getInstructions(function.getBody(), true);
                for (Instruction instruction : instructions) {
                    writer.println(instruction.getAddress() + "  "
                        + String.format("%-24s", hexBytes(instruction.getBytes())) + instruction);
                }
            }
        }
    }
}
