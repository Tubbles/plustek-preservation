// Write the defined members of every class structure as tab separated lines:
// class, offset, type, name, comment, structure length (the members
// ApplyEngineTypes.java placed; empty filler is left out).
//
// Arguments: <output file>
//@category PlustekRE

import java.io.File;
import java.io.PrintWriter;
import java.util.Iterator;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.DataTypeComponent;
import ghidra.program.model.data.Structure;
import ghidra.program.model.listing.GhidraClass;
import ghidra.program.model.listing.VariableUtilities;

public class DumpClassMembers extends GhidraScript {

    @Override
    public void run() throws Exception {
        File outputFile = new File(getScriptArgs()[0]);
        outputFile.getAbsoluteFile().getParentFile().mkdirs();
        try (PrintWriter writer = new PrintWriter(outputFile)) {
            writer.println("class\toffset\ttype\tname\tcomment\tstructure_length");
            Iterator<GhidraClass> classes = currentProgram.getSymbolTable().getClassNamespaces();
            while (classes.hasNext()) {
                GhidraClass ghidraClass = classes.next();
                Structure structure = VariableUtilities.findExistingClassStruct(ghidraClass, currentProgram.getDataTypeManager());
                if (structure == null) {
                    continue;
                }
                for (DataTypeComponent component : structure.getDefinedComponents()) {
                    String comment = component.getComment() == null ? "" : component.getComment().replace('\t', ' ');
                    writer.println(ghidraClass.getName() + "\t" + Integer.toHexString(component.getOffset()) + "\t"
                        + component.getDataType().getDisplayName() + "\t" + component.getFieldName() + "\t" + comment + "\t"
                        + Integer.toHexString(structure.getLength()));
                }
            }
        }
    }
}
