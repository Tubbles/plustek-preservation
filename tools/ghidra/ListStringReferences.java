// For every defined string in the program, write one tab separated line per
// reference: string address, referencing instruction, containing function and
// the string text. Strings without references get one line with "-". Used to
// anchor functions of a binary without symbols (the Windows engine) by their
// log messages and registry value names.
//
// Arguments: <output file>
//@category PlustekRE

import java.io.File;
import java.io.PrintWriter;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class ListStringReferences extends GhidraScript {

    private static String printable(String text) {
        return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n");
    }

    private String functionNameAt(Reference reference) {
        Function function = getFunctionContaining(reference.getFromAddress());
        return function == null ? "?" : function.getName(true) + "@" + function.getEntryPoint();
    }

    @Override
    public void run() throws Exception {
        File outputFile = new File(getScriptArgs()[0]);
        try (PrintWriter writer = new PrintWriter(outputFile)) {
            DataIterator iterator = currentProgram.getListing().getDefinedData(true);
            for (Data data : iterator) {
                if (!data.hasStringValue()) {
                    continue;
                }
                String text = printable(String.valueOf(data.getValue()));
                Reference[] references = getReferencesTo(data.getAddress());
                if (references.length == 0) {
                    writer.println(data.getAddress() + "\t-\t-\t" + text);
                    continue;
                }
                for (Reference reference : references) {
                    writer.println(data.getAddress() + "\t" + reference.getFromAddress() + "\t"
                        + functionNameAt(reference) + "\t" + text);
                }
            }
        }
    }
}
