// List every instruction that carries one of the given scalar values as an
// operand, with the containing function. Used to find where the engine builds
// specific USB request codes or identity values (for example 0x26fe, 0x07b3).
//
// Arguments: <output file> <value> [<value> ...]   (values in hex, 0x prefix optional)
//@category PlustekRE

import java.io.File;
import java.io.PrintWriter;
import java.util.HashSet;
import java.util.Set;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;

public class FindScalars extends GhidraScript {

    private static long parseHex(String text) {
        String digits = text.toLowerCase().startsWith("0x") ? text.substring(2) : text;
        return Long.parseUnsignedLong(digits, 16);
    }

    private Set<Long> scalarValuesOf(Instruction instruction) {
        Set<Long> values = new HashSet<>();
        for (int operand = 0; operand < instruction.getNumOperands(); operand++) {
            for (Object object : instruction.getOpObjects(operand)) {
                if (object instanceof Scalar) {
                    values.add(((Scalar) object).getUnsignedValue());
                }
            }
        }
        return values;
    }

    @Override
    public void run() throws Exception {
        String[] arguments = getScriptArgs();
        File outputFile = new File(arguments[0]);
        Set<Long> wanted = new HashSet<>();
        for (int index = 1; index < arguments.length; index++) {
            wanted.add(parseHex(arguments[index]));
        }
        try (PrintWriter writer = new PrintWriter(outputFile)) {
            InstructionIterator instructions = currentProgram.getListing().getInstructions(true);
            for (Instruction instruction : instructions) {
                Set<Long> values = scalarValuesOf(instruction);
                values.retainAll(wanted);
                if (values.isEmpty()) {
                    continue;
                }
                Function function = getFunctionContaining(instruction.getAddress());
                String functionName = function == null ? "?" : function.getName(true);
                for (Long value : values) {
                    writer.println(String.format("0x%x\t%s\t%s\t%s", value,
                        instruction.getAddress(), functionName, instruction));
                }
            }
        }
    }
}
