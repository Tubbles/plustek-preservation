"""Tests for reconstruct_engine.py on snippets captured from the Ghidra output.

Run: python3 -I -B -m unittest discover -s tools/ghidra
"""

import textwrap
import unittest

import reconstruct_engine as engine


def dedent(text: str) -> str:
    return textwrap.dedent(text).strip("\n")


MOTOR_SEL = dedent("""
    bool __thiscall CAsic::MotorSel(CAsic *this,int param_1)

    {
      byte bVar1;
      int *piVar3;
      bool local_16;
      byte local_15;
      int local_14;
      CAsic *local_10;

      local_14 = param_1;
      local_10 = this;
      LogToConsole(5,"CAsic.MotorSel.IN Source = %d\\n",(ulong)(uint)param_1);
      local_16 = false;
      piVar3 = CRegistry::MotorReg((CRegistry *)((long)&this->vptr + ADJ(this->vptr)->CRegistryOffset));
      if (*piVar3 != 0) {
        piVar3 = CRegistry::MotorReg((CRegistry *)((long)&this->vptr + ADJ(this->vptr)->CRegistryOffset)
                                    );
        bVar1 = (byte)*piVar3;
        CIOUSB::ReadReg((CIOUSB *)((long)&this->vptr + ADJ(this->vptr)->CIOUSBOffset),(ushort)bVar1,
                        &local_15,0);
        if (local_14 == -1) {
          _MTRPWR(this,0,true,0);
        }
      }
      return local_16;
    }
""")

CONTEXT = {
    "static_member_names": frozenset({"CRegister::Big2LittleEndian"}),
    "free_function_names": {"LogToConsole"},
    "virtual_bases": {"CAsic": {"CRegistry", "CIOUSB", "CGL128"}},
    "slot_names": {("CIOUSB", 0x10): "Bcd"},
    "methods": {"CAsic": {"MotorSel", "_MTRPWR"}},
    "registry_keys": {"MotorReg": "MotorReg", "ProductID": "ProudctID"},
    "registry_entries": {0x66: "MotorReg"},
    "structure_lengths": {"CAsic": 0x8178},
}


class ParsingTest(unittest.TestCase):

    def test_parse_decompiled_text_takes_plate_and_definition(self):
        text = "// CAsic::MotorSel at 0005d5f0\n// signature: bool MotorSel(CAsic * this, int param_1)\n\n/* CAsic::MotorSel(int) */\n\n" + MOTOR_SEL
        demangled, definition = engine.parse_decompiled_text(text)
        self.assertEqual(demangled, "CAsic::MotorSel(int)")
        self.assertTrue(definition.startswith("bool __thiscall CAsic::MotorSel("))

    def header(self, head: str) -> str:
        return ("// CIOUSB::WriteRegs at 000f2eb0\n// signature: bool WriteRegs(CIOUSB * this, ushort param_1)\n\n"
                "/* CIOUSB::WriteRegs(unsigned short) */\n\n" + head + "\n\n{\n  return true;\n}\n")

    def test_two_line_head_with_thiscall(self):
        _, definition = engine.parse_decompiled_text(self.header("bool __thiscall\nCIOUSB::WriteRegs(CIOUSB *this,ushort param_1)"))
        self.assertTrue(definition.startswith("bool __thiscall CIOUSB::WriteRegs(CIOUSB *this,ushort param_1)\n\n{"))
        self.assertNotIn("signature", definition)

    def test_two_line_head_without_thiscall(self):
        _, definition = engine.parse_decompiled_text(self.header("undefined8\nCRegister::Big2LittleEndian(uchar *param_1,int param_2)"))
        self.assertEqual(definition.split("\n")[0], "undefined8 CRegister::Big2LittleEndian(uchar *param_1,int param_2)")

    def test_three_line_head_with_thiscall(self):
        head = "bool __thiscall\nCIOUSB::WriteRegBit(CIOUSB *this,ushort param_1,uchar param_2,\n                   bool param_5)"
        _, definition = engine.parse_decompiled_text(self.header(head))
        self.assertEqual(definition.split("\n")[0], "bool __thiscall CIOUSB::WriteRegBit(CIOUSB *this,ushort param_1,uchar param_2,bool param_5)")

    def test_three_line_head_without_thiscall(self):
        head = "int\nCScan::Helper(int param_1,int param_2,int param_3,int param_4,\n             int param_5)"
        _, definition = engine.parse_decompiled_text(self.header(head))
        self.assertEqual(definition.split("\n")[0], "int CScan::Helper(int param_1,int param_2,int param_3,int param_4,int param_5)")

    def test_four_line_head(self):
        head = "void __thiscall\nCScan::GetShadingAddrSizeFromFlash\n          (CScan *this,uint *param_1,\n          bool param_8)"
        _, definition = engine.parse_decompiled_text(self.header(head))
        self.assertEqual(definition.split("\n")[0], "void __thiscall CScan::GetShadingAddrSizeFromFlash(CScan *this,uint *param_1,bool param_8)")

    def test_wrapped_head_keeps_member_non_static(self):
        _, definition = engine.parse_decompiled_text(self.header("bool __thiscall\nCIOUSB::WriteRegs(CIOUSB *this,ushort param_1)"))
        function = engine.Function(0xf2eb0, "CIOUSB::WriteRegs", "CIOUSB::WriteRegs(unsigned short)", definition)
        self.assertEqual(engine.static_member_addresses([function]), set())
        self.assertEqual(engine.method_declaration(function, False, False), "bool WriteRegs(unsigned short);")

    def test_class_purposes_takes_first_sentence(self):
        markdown = "- `CIOUSB`: the USB transport. Register access (`ReadReg`).\n- `CGL128` (also `CGL125`): one accessor per field.\n"
        purposes = engine.class_purposes(markdown, {"CIOUSB", "CGL128"})
        self.assertEqual(purposes, {"CIOUSB": "the USB transport.", "CGL128": "one accessor per field."})

    def test_class_purposes_cover_the_also_list(self):
        markdown = "- `CGL128` (also `CGL125`, `CGL126`): one accessor per field.\n"
        self.assertEqual(engine.class_purposes(markdown, {"CGL128", "CGL126"}), {"CGL128": "one accessor per field.", "CGL126": "one accessor per field."})

    def test_called_classes(self):
        text = "  registry()->MotorReg();\n  usb()->ReadReg(1);\n  CScan::Foo(x);\n  LogToConsole(5);"
        self.assertEqual(engine.called_classes(text, {"CRegistry", "CIOUSB"}), {"CRegistry": 1, "CIOUSB": 1, "CScan": 1})


class PlacementTest(unittest.TestCase):

    def entry(self, linkage, unit="Asic.cpp", first_seen=()):
        return engine.MapEntry(0x5000, "__ZN5CAsic8_LPERIODEbi", unit, unit.replace(".cpp", ".o"), linkage, first_seen)

    def test_inline_member_goes_to_class_header(self):
        function = engine.Function(0x5000, "CAsic::_LPERIOD", "", "")
        placement = engine.place_function(function, self.entry("inline"), {"Asic.cpp": "Sources"}, {"CAsic": "Includes/Asic.h"})
        self.assertEqual(placement, engine.Placement("Includes/Asic.h", True))

    def test_external_member_stays_in_its_compile_unit(self):
        function = engine.Function(0x5000, "CAsic::_LPERIOD", "", "")
        placement = engine.place_function(function, self.entry("external", "AddOn.cpp"), {"AddOn.cpp": "Sources"}, {})
        self.assertEqual(placement, engine.Placement("Sources/AddOn.cpp", False))

    def test_filmapi_unit_keeps_its_directory(self):
        function = engine.Function(0x1000, "memset", "", "")
        entries = {1: self.entry("external", "MAPTOOLS.cpp", ("FilmApi/MAPTOOLS.cpp",))}
        directories = engine.unit_directories(entries)
        self.assertEqual(engine.place_function(function, entries[1], directories, {}).path, "FilmApi/MAPTOOLS.cpp")

    def test_function_without_map_entry_is_unmapped(self):
        function = engine.Function(0xf9136, "_memset", "", "")
        self.assertEqual(engine.place_function(function, None, {}, {}).path, engine.UNMAPPED_PATH)

    def test_header_spelling_prefers_exact_class_stem(self):
        self.assertEqual(engine.preferred_header("CIOUSB", {"Includes/Usb.h", "Includes/USB.h"}), "Includes/USB.h")
        self.assertEqual(engine.preferred_header("CNotify", {"Includes/notify.h"}), "Includes/notify.h")

    def test_class_headers_come_from_first_seen_files(self):
        entries = {0x2da0: engine.MapEntry(0x2da0, "__ZN6CIOUSB3BcdEv", "AD9826.cpp", "AD9826.o", "inline", ("Includes/Usb.h",))}
        self.assertEqual(engine.class_headers(entries, {0x2da0: "CIOUSB::Bcd"}), {"CIOUSB": "Includes/Usb.h"})

    def test_other_header_spellings_are_listed_by_the_chosen_one(self):
        entries = {
            0x2da0: engine.MapEntry(0x2da0, "__ZN6CIOUSB3BcdEv", "AD9826.cpp", "AD9826.o", "inline", ("Includes/Usb.h",)),
            0x51a0: engine.MapEntry(0x51a0, "__ZN6CIOUSB3BcdEt", "AddOn.cpp", "AddOn.o", "inline", ("Includes/USB.h",)),
        }
        names = {0x2da0: "CIOUSB::Bcd", 0x51a0: "CIOUSB::Bcd"}
        self.assertEqual(engine.other_header_spellings(entries, names), {"Includes/USB.h": ["Includes/Usb.h"]})


class NameTest(unittest.TestCase):

    def test_helper_names(self):
        self.assertEqual(engine.helper_name("CRegistry"), "registry")
        self.assertEqual(engine.helper_name("CIOUSB"), "usb")
        self.assertEqual(engine.helper_name("CRegister"), "registers")
        self.assertEqual(engine.helper_name("CGL846"), "gl846")
        self.assertEqual(engine.helper_name("CHT82V36"), "ht82v36")
        self.assertEqual(engine.helper_name("CAddOn"), "addOn")

    def test_method_declaration_uses_demangled_parameters(self):
        function = engine.Function(0xf2670, "CIOUSB::ReadReg", "CIOUSB::ReadReg(unsigned short, unsigned char*, int)",
                                   "bool __thiscall CIOUSB::ReadReg(CIOUSB *this,ushort param_1,uchar *param_2,int param_3)\n\n{\n}")
        self.assertEqual(engine.method_declaration(function, False, False), "bool ReadReg(unsigned short, unsigned char*, int);")

    def test_constructor_declaration_has_no_return_type(self):
        function = engine.Function(0x82c00, "CGL128::CGL128", "CGL128::CGL128()", "void __thiscall CGL128::CGL128(CGL128 *this,undefined **vtt)\n\n{\n}")
        self.assertEqual(engine.method_declaration(function, False, False), "CGL128();")


class RewriteTest(unittest.TestCase):

    def test_join_wrapped_lines(self):
        text = "  piVar3 = CRegistry::MotorReg((CRegistry *)\n                               ((long)&this->vptr + x));\n  y = 1;"
        self.assertEqual(engine.join_wrapped_lines(text), "  piVar3 = CRegistry::MotorReg((CRegistry *)((long)&this->vptr + x));\n  y = 1;")

    def test_join_keeps_definition_and_conditions_apart(self):
        text = "bool __thiscall CAsic::IsCis(CAsic *this)\n\n{\n  if ((a != 0) &&\n     (b != 0)) {\n    return true;\n  }\n}"
        joined = engine.join_wrapped_lines(text)
        self.assertIn("bool __thiscall CAsic::IsCis(CAsic *this)\n\n{", joined)
        self.assertIn("  if ((a != 0) && (b != 0)) {", joined)

    def test_definition_line_drops_thiscall_and_this(self):
        self.assertEqual(engine.rewrite_definition_line("bool __thiscall CAsic::MotorSel(CAsic *this,int param_1)\n{", False),
                         "bool CAsic::MotorSel(int param_1)\n{")
        self.assertEqual(engine.rewrite_definition_line("bool __thiscall CAsic::IsCis(CAsic *this)\n{", True),
                         "inline bool CAsic::IsCis(void)\n{")

    def test_virtual_base_cast_becomes_helper(self):
        text = "CRegistry::MotorReg((CRegistry *)((long)&this->vptr + ADJ(this->vptr)->CRegistryOffset));"
        self.assertEqual(engine.rewrite_virtual_base_casts(text, {"CRegistry"}), "CRegistry::MotorReg(registry());")

    def test_virtual_base_cast_to_other_type_keeps_the_cast(self):
        text = "x = (CAsic *)((long)&this->vptr + ADJ(this->vptr)->CRegistryOffset);"
        self.assertEqual(engine.rewrite_virtual_base_casts(text, {"CRegistry"}), "x = (CAsic *)registry();")

    def test_unknown_virtual_base_is_left_alone(self):
        text = "f((CMap *)((long)&this->vptr + ADJ(this->vptr)->CMapOffset));"
        self.assertEqual(engine.rewrite_virtual_base_casts(text, {"CRegistry"}), text)

    def test_adjusted_access_with_dot(self):
        self.assertEqual(engine.normalize_adjusted_access("ADJ(this->vptr).CGL128Offset"), "ADJ(this->vptr)->CGL128Offset")

    def test_base_member_call(self):
        self.assertEqual(engine.rewrite_base_member_calls("CRegistry::MotorReg(registry());", {"CRegistry"}), "registry()->MotorReg();")
        self.assertEqual(engine.rewrite_base_member_calls("CIOUSB::ReadReg(usb(),(ushort)bVar1,&local_15,0);", {"CIOUSB"}),
                         "usb()->ReadReg((ushort)bVar1,&local_15,0);")

    def test_static_member_is_not_called_through_the_helper(self):
        text = "CRegister::Big2LittleEndian(registers(),2);"
        self.assertEqual(engine.rewrite_base_member_calls(text, {"CRegister"}, frozenset({"CRegister::Big2LittleEndian"})), text)

    def test_base_member_call_needs_matching_helper(self):
        text = "CScan::GetMyLastError(registry());"
        self.assertEqual(engine.rewrite_base_member_calls(text, {"CScan", "CRegistry"}), text)

    def test_virtual_call_through_temporary(self):
        text = dedent("""
              lVar1 = ADJ(this->vptr)->CIOUSBOffset;
              uVar2 = (**(code **)(*(long *)((long)&this->vptr + lVar1) + 0x10))((long)&this->vptr + lVar1);
              if (uVar2 < 0x704) {
                lVar1 = ADJ(this->vptr)->CIOUSBOffset;
        """)
        folded = engine.fold_virtual_base_temporaries(text, {"CIOUSB"})
        called = engine.rewrite_virtual_calls(folded, {"CIOUSB"}, {("CIOUSB", 0x10): "Bcd"})
        self.assertEqual(called.split("\n")[0], "uVar2 = usb()->Bcd();")

    def test_virtual_call_after_cast_cleanup(self):
        text = "uVar2 = (**(code **)(*(long *)usb() + 0x10))((long)usb());"
        self.assertEqual(engine.rewrite_virtual_calls(text, {"CIOUSB"}, {("CIOUSB", 0x10): "Bcd"}), "uVar2 = usb()->Bcd();")

    def test_virtual_call_to_unknown_slot_is_kept(self):
        text = "uVar2 = (**(code **)(*(long *)usb() + 0x18))((long)usb());"
        self.assertEqual(engine.rewrite_virtual_calls(text, {"CIOUSB"}, {("CIOUSB", 0x10): "Bcd"}), text)

    def test_temporary_read_elsewhere_keeps_its_assignment(self):
        text = "  lVar1 = ADJ(this->vptr)->CIOUSBOffset;\n  f((long)&this->vptr + lVar1);\n  g(lVar1);"
        self.assertEqual(engine.fold_virtual_base_temporaries(text, {"CIOUSB"}),
                         "  lVar1 = ADJ(this->vptr)->CIOUSBOffset;\n  f((long)usb());\n  g(lVar1);")

    def test_temporary_used_two_statements_later(self):
        text = ("  long lVar1;\n  lVar1 = ADJ(this->vptr)->CAsicOffset;\n  piVar4 = registry()->LedGreenID();\n"
                "  CAsic::LedOn((CAsic *)((long)&this->vptr + lVar1),*piVar4,true,true);")
        folded = engine.fold_virtual_base_temporaries(text, {"CAsic"})
        cast = engine.rewrite_virtual_base_casts(folded, {"CAsic"})
        self.assertEqual(engine.rewrite_base_member_calls(cast, {"CAsic"}),
                         "  piVar4 = registry()->LedGreenID();\n  asic()->LedOn(*piVar4,true,true);")

    def test_temporary_holding_two_bases_is_folded_in_straight_lines(self):
        text = ("  lVar1 = ADJ(this->vptr)->CAsicOffset;\n  x = 1;\n  f((long)&this->vptr + lVar1);\n"
                "  lVar1 = ADJ(this->vptr)->CIOUSBOffset;\n  g((long)&this->vptr + lVar1);")
        self.assertEqual(engine.fold_virtual_base_temporaries(text, {"CAsic", "CIOUSB"}), "  x = 1;\n  f((long)asic());\n  g((long)usb());")

    def test_temporary_with_two_bases_across_a_branch_is_kept(self):
        text = ("  if (a) {\n    lVar1 = ADJ(this->vptr)->CAsicOffset;\n  }\n  else {\n    lVar1 = ADJ(this->vptr)->CIOUSBOffset;\n  }\n"
                "  f((long)&this->vptr + lVar1);")
        self.assertEqual(engine.fold_virtual_base_temporaries(text, {"CAsic", "CIOUSB"}), text)

    def test_store_overwritten_in_the_same_block_is_dropped(self):
        text = ("  lVar3 = ADJ(this->vptr)->CAsicOffset;\n  if (b) {\n    x = 1;\n  }\n  lVar3 = ADJ(this->vptr)->CIOUSBOffset;\n"
                "  if (a) {\n    g(lVar3);\n  }")
        self.assertEqual(engine.drop_dead_temporary_stores(text, "lVar3"), text.split("\n", 1)[1])

    def test_member_call_line_is_not_a_label(self):
        text = ("  lVar1 = ADJ(this->vptr)->CAsicOffset;\n  CAsic::LedOn(asic(),1,true,true);\n"
                "  lVar1 = ADJ(this->vptr)->CIOUSBOffset;\n  g(lVar1);")
        self.assertEqual(engine.drop_dead_temporary_stores(text, "lVar1"), text.split("\n", 1)[1])

    def test_label_stops_the_dead_store_scan(self):
        text = "  lVar1 = ADJ(this->vptr)->CAsicOffset;\nLAB_0003a1b2:\n  lVar1 = ADJ(this->vptr)->CIOUSBOffset;"
        self.assertEqual(engine.drop_dead_temporary_stores(text, "lVar1"), text)

    def test_store_in_a_comma_expression_keeps_the_temporary(self):
        text = ("  long lVar1;\n  lVar1 = ADJ(this->vptr)->CIOUSBOffset;\n  f((long)&this->vptr + lVar1);\n"
                "  if ((lVar1 = ADJ(this->vptr)->CIOUSBOffset,uVar2 = g(), 0x605 < uVar2)) {\n    h(lVar1);\n  }")
        result = engine.fold_virtual_base_temporaries(text, {"CIOUSB"})
        self.assertIn("  long lVar1;", result)
        self.assertIn("(lVar1 = ADJ(this->vptr)->CIOUSBOffset,uVar2 = g(), 0x605 < uVar2)", result)
        self.assertIn("f((long)usb());", result)

    def test_unread_temporary_stored_in_a_comma_expression_is_dropped(self):
        text = ("  long lVar1;\n  lVar1 = ADJ(this->vptr)->CIOUSBOffset;\n  uVar3 = usb()->Bcd();\n  if (uVar3 < 0x6a6) {\n"
                "    lVar1 = ADJ(this->vptr)->CIOUSBOffset;\n"
                "    if ((uVar3 < 0x400) || (lVar1 = ADJ(this->vptr)->CIOUSBOffset,uVar3 = usb()->Bcd(), 0x605 < uVar3)) {\n"
                "      x = 1;\n    }\n  }")
        self.assertEqual(engine.drop_unused_temporary(text, "lVar1"),
                         "  uVar3 = usb()->Bcd();\n  if (uVar3 < 0x6a6) {\n"
                         "    if ((uVar3 < 0x400) || (uVar3 = usb()->Bcd(), 0x605 < uVar3)) {\n      x = 1;\n    }\n  }")

    def test_store_read_in_between_is_kept(self):
        text = "  lVar3 = ADJ(this->vptr)->CAsicOffset;\n  if (b) {\n    g(lVar3);\n  }\n  lVar3 = ADJ(this->vptr)->CIOUSBOffset;"
        self.assertEqual(engine.drop_dead_temporary_stores(text, "lVar3"), text)

    def test_store_before_a_block_exit_is_kept(self):
        text = "  if (b) {\n    lVar3 = ADJ(this->vptr)->CAsicOffset;\n  }\n  lVar3 = ADJ(this->vptr)->CIOUSBOffset;"
        self.assertEqual(engine.drop_dead_temporary_stores(text, "lVar3"), text)

    def test_join_does_not_space_after_arrow(self):
        self.assertEqual(engine.join_wrapped_lines("  f(ADJ(this->vptr)->\n    CAsicOffset);"), "  f(ADJ(this->vptr)->CAsicOffset);")

    def test_temporary_used_in_a_nested_block_keeps_its_assignment(self):
        text = ("  lVar1 = ADJ(this->vptr)->CAsicOffset;\n  f((long)&this->vptr + lVar1);\n  if (a) {\n    g((long)&this->vptr + lVar1);\n  }\n"
                "  lVar1 = ADJ(this->vptr)->CIOUSBOffset;")
        result = engine.fold_virtual_base_temporaries(text, {"CAsic", "CIOUSB"})
        self.assertIn("  lVar1 = ADJ(this->vptr)->CAsicOffset;\n  f((long)asic());", result)
        self.assertIn("g((long)&this->vptr + lVar1);", result)

    def test_field_of_virtual_base(self):
        text = "if (*(int *)(&this->field_0x240 + ADJ(this->vptr)->CRegistryOffset) == 6) {"
        self.assertEqual(engine.rewrite_virtual_base_fields(text, {"CRegistry"}, 0x8178),
                         "if (*(int *)((undefined *)registry() + 0x240) == 6) {")

    def test_field_past_the_structure_end(self):
        text = "if (((&this[0x18].field_0xd)[ADJ(this->vptr)->CRegistryOffset] & 1) == 1) {"
        self.assertEqual(engine.rewrite_virtual_base_fields(text, {"CRegistry"}, 0x10),
                         "if ((((undefined *)registry())[0x18d] & 1) == 1) {")

    def test_field_past_the_end_needs_the_length(self):
        text = "x = (&this[2].field_0xd)[ADJ(this->vptr)->CRegistryOffset];"
        self.assertEqual(engine.rewrite_virtual_base_fields(text, {"CRegistry"}, None), text)

    def test_own_virtual_call(self):
        text = "(*(code *)ADJ(this->vptr)->SetSevenSegment)(this,local_14,1);"
        self.assertEqual(engine.rewrite_virtual_calls(text, set(), {}), "SetSevenSegment(local_14,1);")

    def test_own_member_call_drops_this(self):
        text = "_MTRPWR(this,0,true,0);\nIsCis(this);\nLogToConsole(this,1);"
        self.assertEqual(engine.rewrite_own_member_calls(text, {"_MTRPWR", "IsCis"}), "_MTRPWR(0,true,0);\nIsCis();\nLogToConsole(this,1);")

    def test_registry_key_annotation_only_when_different(self):
        text = "a = registry()->MotorReg(); b = registry()->ProductID();"
        self.assertEqual(engine.annotate_registry_keys(text, CONTEXT["registry_keys"]),
                         'a = registry()->MotorReg(); b = registry()->ProductID() /* plist key "ProudctID" */;')

    def test_property_entry_gets_its_key(self):
        text = "  return this->propertyValues + m_prop[0x66].index;"
        self.assertEqual(engine.annotate_property_entries(text, {0x66: "MotorReg"}), text + '  // plist key "MotorReg"')

    def test_accessor_keys_from_property_table_index(self):
        function = engine.Function(0x39380, "CRegistry::MotorReg", "", "int * __thiscall CRegistry::MotorReg(CRegistry *this)\n\n{\n  return this->propertyValues + m_prop[0x66].index;\n}")
        self.assertEqual(engine.accessor_keys([function], {0x66: "MotorReg"}), {"MotorReg": "MotorReg"})


class LocalsTest(unittest.TestCase):

    def test_spill_with_equal_type_is_folded(self):
        result = engine.fold_parameter_spills(MOTOR_SEL)
        self.assertNotIn("local_14", result)
        self.assertIn("if (param_1 == -1)", result)
        self.assertNotIn("local_10", result)

    def test_spill_with_other_type_is_kept(self):
        text = MOTOR_SEL.replace("  int local_14;", "  uint local_14;")
        result = engine.fold_parameter_spills(text)
        self.assertIn("local_14 = param_1;", result)

    def test_spill_of_changed_local_is_kept(self):
        text = MOTOR_SEL.replace("  return local_16;", "  local_14 = 3;\n  return local_16;")
        self.assertIn("local_14 = param_1;", engine.fold_parameter_spills(text))

    def test_store_through_a_spilled_pointer_does_not_block_folding(self):
        text = MOTOR_SEL.replace("  int local_14;", "  int *local_14;").replace("(CAsic *this,int param_1)", "(CAsic *this,int *param_1)")
        text = text.replace("  return local_16;", "  *local_14 = 3;\n  return local_16;")
        self.assertIn("*param_1 = 3;", engine.fold_parameter_spills(text))

    def test_spill_after_a_read_of_the_local_is_kept(self):
        text = MOTOR_SEL.replace("  local_14 = param_1;", "  f(local_14);\n  local_14 = param_1;")
        self.assertIn("local_14 = param_1;", engine.fold_parameter_spills(text))

    def test_spill_of_reassigned_parameter_is_kept(self):
        text = MOTOR_SEL.replace("  return local_16;", "  param_1 = 0;\n  return local_16;")
        self.assertIn("local_14 = param_1;", engine.fold_parameter_spills(text))

    def test_spill_assigned_in_a_comma_expression_is_kept(self):
        text = MOTOR_SEL.replace("  return local_16;", "  if ((local_14 = 3, f())) {\n  }\n  return local_16;")
        self.assertIn("local_14 = param_1;", engine.fold_parameter_spills(text))

    def test_spill_whose_address_is_taken_is_kept(self):
        text = MOTOR_SEL.replace("&local_15", "&local_14")
        self.assertIn("local_14 = param_1;", engine.fold_parameter_spills(text))

    def test_dead_local_is_dropped(self):
        text = dedent("""
            bool CAsic::IsCis(void)

            {
              int iVar1;
              CAsic *local_10;

              local_10 = this;
              return true;
            }
        """)
        result = engine.drop_dead_locals(text)
        self.assertNotIn("iVar1", result)
        self.assertNotIn("local_10", result)
        self.assertIn("return true;", result)

    def test_read_local_is_kept(self):
        text = "bool f(void)\n\n{\n  int local_10;\n  \n  local_10 = 1;\n  return local_10;\n}"
        self.assertEqual(engine.drop_dead_locals(text), text)


class RenderTest(unittest.TestCase):

    def test_reconstructed_names_used_in_a_file(self):
        context = {"virtual_bases": {"CGL128": {"CIOUSB", "CRegister"}},
                   "members": [engine.Member("CGL128", 0x10, "ushort *", "regShadow", "reconstructed: set by the constructor"),
                               engine.Member("CRegister", 0x8, "ushort[288]", "m_reg", "named after CRegister::Dump_m_reg_ToConsole")]}
        texts = ["  this->regShadow[2] = 1;\n  usb()->WriteRegs(2,this->regBuf + 2);\n  x = m_prop[0x66].index;"]
        self.assertEqual(engine.reconstructed_names(texts, context), ["usb()", "regShadow", "m_prop[].index"])

    def test_symbol_variants(self):
        self.assertEqual(engine.symbol_variant("__ZN5CAsicC2Ev"), "C2 base object")
        self.assertEqual(engine.symbol_variant("__ZN6CGL128D0Ev"), "D0 deleting")
        self.assertEqual(engine.symbol_variant("__ZTv0_n40_N7CAD9826D1Ev"), "thunk")
        self.assertEqual(engine.symbol_variant("__ZN5CAsic8MotorSelEi"), "")


class WholeFunctionTest(unittest.TestCase):

    def test_motor_sel(self):
        function = engine.Function(0x5d5f0, "CAsic::MotorSel", "CAsic::MotorSel(int)", MOTOR_SEL)
        result = engine.rewrite_function(function, CONTEXT, False)
        self.assertTrue(result.startswith("bool CAsic::MotorSel(int param_1)"))
        self.assertIn("piVar3 = registry()->MotorReg();", result)
        self.assertIn("usb()->ReadReg((ushort)bVar1,&local_15,0);", result)
        self.assertIn("_MTRPWR(0,true,0);", result)
        self.assertIn("if (param_1 == -1)", result)


if __name__ == "__main__":
    unittest.main()
