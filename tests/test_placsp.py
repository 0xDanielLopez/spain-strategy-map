"""PLACSP source: privacy rules and aggregation on SYNTHETIC entries only (invented names and ids)."""

import io
import unittest
import xml.etree.ElementTree as ET

from pipeline.sources import placsp


def make_cif(letter: str, digits7: str, as_letter: bool = False) -> str:
    total = 0
    for pos, c in enumerate(digits7, start=1):
        d = int(c)
        total += d if pos % 2 == 0 else sum(int(x) for x in str(2 * d))
    control = (10 - total % 10) % 10
    return letter + digits7 + ("JABCDEFGHI"[control] if as_letter else str(control))


GOOD = make_cif("B", "1234567")
GOOD_LETTER = make_cif("Q", "7654321", as_letter=True)


def bad_control(cif: str) -> str:
    last = cif[-1]
    return cif[:-1] + ("0" if last != "0" else "1")


class WinnerTest(unittest.TestCase):
    def test_valid_cif_is_publishable(self):
        self.assertEqual(placsp.publishable_winner(GOOD, "Empresa  Inventada SL"), ("Empresa Inventada SL", GOOD))
        self.assertEqual(placsp.publishable_winner(GOOD_LETTER, "Obras Ficticias SA")[1], GOOD_LETTER)

    def test_normalisation(self):
        spaced = f"{GOOD[0]} {GOOD[1:4]}.{GOOD[4:8]}-{GOOD[8]}".lower()
        self.assertEqual(placsp.publishable_winner(spaced, "Ficticia SL")[1], GOOD)

    def test_control_digit_must_be_valid(self):
        self.assertIsNone(placsp.publishable_winner(bad_control(GOOD), "Ficticia SL"))

    def test_quarantine_cases(self):
        for raw in ("12345678Z", "X1234567L", "Y1234567X", "K1234567A", "L1234567A", "M1234567A",
                    make_cif("E", "1234567"), make_cif("H", "1234567"), make_cif("J", "1234567"),
                    make_cif("U", "1234567"), make_cif("V", "1234567"), "***4567**", "", "Pendiente", None,
                    "FR12345678901", "B123"):
            self.assertIsNone(placsp.publishable_winner(raw, "Nombre Inventado"), raw)

    def test_personal_title_in_name(self):
        for name in ("D. Juan Ficticio", "Dña. Ana Inventada", "Don Pedro Falso SL", "Doña Rosa Falsa"):
            self.assertIsNone(placsp.publishable_winner(GOOD, name), name)
        self.assertIsNotNone(placsp.publishable_winner(GOOD, "Dones del Valle SL"))

    def test_personal_markers_in_name(self):
        """Synthetic names only. A valid CIF does not save a name that carries a person, a document or a contact."""
        bad = ("DÑA. ANA INVENTADA", "Dª Ana Inventada", "D.ª Ana Inventada", "D.Juan Ficticio", "don pedro falso sl",
               "DOÑA ROSA FALSA", "Sr. Falso Inventado", "Sra. Falsa", "Hijos de Ficticio Falso SL",
               "Hermanos Falso Inventado SL", "Viuda de Falso SA", "Ficticio Falso, Juan (12345678Z)",
               "Ficticia SL 12.345.678-z", "Ficticia SL x-1234567-l", "Ficticia SL ***4567**",
               "Ficticia SL contacto@ficticia.example", "Ficticia SL www.ficticia.example",
               "Ficticia SL 600 123 456", "Ficticia SL +34 912345678", "D\u200b. Juan Ficticio",
               "\uff24. Juan Ficticio", "Servicios Don Benito Inventados SL", "Sr Falso Inventado")
        for name in bad:
            self.assertIsNone(placsp.publishable_winner(GOOD, name), name)
        for name in ("Construcciones Ficticias SL", "Dones del Valle SL", "Donosti Obras Inventadas SA",
                     "Srandom Ficticia SL", "Ficticia 2025 SL"):
            self.assertIsNotNone(placsp.publishable_winner(GOOD, name), name)

    def test_control_type_by_entity_letter(self):
        """A and B carry a digit, N P Q R S W a letter: the other form is rejected."""
        b = make_cif("B", "1234567")
        digit = b[-1] if b[-1].isdigit() else str("JABCDEFGHI".index(b[-1]))
        self.assertIsNotNone(placsp.publishable_winner("B1234567" + digit, "Ficticia SL"))
        self.assertIsNone(placsp.publishable_winner("B1234567" + "JABCDEFGHI"[int(digit)], "Ficticia SL"))
        self.assertIsNotNone(placsp.publishable_winner("Q1234567" + "JABCDEFGHI"[int(digit)], "Organismo Inventado"))
        self.assertIsNone(placsp.publishable_winner("Q1234567" + digit, "Organismo Inventado"))

    def test_safe_title_markers(self):
        for t in ("Servicio para DÑA. ANA FALSA", "Alta de x1234567l", "Pago a 12.345.678-Z", "Contacto 600123456",
                  "Informes a info@ficticia.example", "Servicio Sr. Falso", "Expediente de D.ª Ana Falsa",
                  "Pago a Don Benito Falso Inventado", "Finca de Dª Rosa Falsa"):
            self.assertIsNone(placsp.safe_title(t), t)
        for t in ("Obras en Don Benito, fase 2", "Pavimentación en Doña Mencía", "Suministro de 12345678 unidades",
                  "Piscina de Valencia de Don Juan", "Camino de La Almunia de Doña Godina", "Obras en Don Benito",
                  "Lote 3: 2.500.000 euros", "Obra 2025/000123 calle Mayor", "Servicio I+D de alumbrado"):
            self.assertIsNotNone(placsp.safe_title(t), t)

    def test_safe_body(self):
        self.assertEqual(placsp.safe_body("Ayuntamiento de  Don Benito"), "Ayuntamiento de Don Benito")
        self.assertIsNone(placsp.safe_body("Ayuntamiento Inventado contacto@ficticio.example"))
        self.assertIsNone(placsp.safe_body(""))

    def test_empty_name_is_quarantine(self):
        self.assertIsNone(placsp.publishable_winner(GOOD, "  "))

    def test_safe_title(self):
        self.assertEqual(placsp.safe_title("Obras de  pavimentacion"), "Obras de pavimentacion")
        self.assertEqual(len(placsp.safe_title("x" * 400)), 160)
        for t in ("Servicio para D. Antonio Falso", "Contrato 12345678Z", "Alta de X1234567L", "", None):
            self.assertIsNone(placsp.safe_title(t), t)


NS = ('xmlns="http://www.w3.org/2005/Atom" xmlns:cbc="urn:cbc" xmlns:cac="urn:cac" '
      'xmlns:cac-place-ext="urn:place"')


def entry_xml(eid, updated, dir3="L01280796", nif_body="P2807900B", folder="F1", results=(), title="Obra inventada",
              proc="1", ptype="3"):
    res = ""
    for code, date, offers, lot, amount, wid, wname in results:
        res += (f"<cac:TenderResult><cbc:ResultCode>{code}</cbc:ResultCode><cbc:AwardDate>{date}</cbc:AwardDate>"
                f"<cbc:ReceivedTenderQuantity>{offers}</cbc:ReceivedTenderQuantity><cac:WinningParty>"
                f'<cac:PartyIdentification><cbc:ID schemeName="NIF">{wid}</cbc:ID></cac:PartyIdentification>'
                f"<cac:PartyName><cbc:Name>{wname}</cbc:Name></cac:PartyName></cac:WinningParty>"
                f"<cac:AwardedTenderedProject><cbc:ProcurementProjectLotID>{lot}</cbc:ProcurementProjectLotID>"
                f"<cac:LegalMonetaryTotal><cbc:TaxExclusiveAmount>{amount}</cbc:TaxExclusiveAmount></cac:LegalMonetaryTotal>"
                f"</cac:AwardedTenderedProject></cac:TenderResult>")
    ids = (f'<cac:PartyIdentification><cbc:ID schemeName="DIR3">{dir3}</cbc:ID></cac:PartyIdentification>' if dir3 else "")
    ids += f'<cac:PartyIdentification><cbc:ID schemeName="NIF">{nif_body}</cbc:ID></cac:PartyIdentification>'
    return (f'<entry {NS}><id>{eid}</id><updated>{updated}</updated><link href="https://example.org/{eid}"/>'
            f"<cac-place-ext:ContractFolderStatus><cbc:ContractFolderID>{folder}</cbc:ContractFolderID>"
            f"<cac-place-ext:LocatedContractingParty><cac:Party>{ids}<cac:PartyName><cbc:Name>Ayuntamiento de Prueba"
            f"</cbc:Name></cac:PartyName></cac:Party></cac-place-ext:LocatedContractingParty>"
            f"<cac:ProcurementProject><cbc:Name>{title}</cbc:Name><cbc:TypeCode>{ptype}</cbc:TypeCode>"
            f"<cac:RequiredCommodityClassification><cbc:ItemClassificationCode>45000000</cbc:ItemClassificationCode>"
            f"</cac:RequiredCommodityClassification></cac:ProcurementProject>{res}"
            f"<cac:TenderingProcess><cbc:ProcedureCode>{proc}</cbc:ProcedureCode></cac:TenderingProcess>"
            f"</cac-place-ext:ContractFolderStatus></entry>")


def parse(xml):
    return placsp.parse_entry(ET.parse(io.StringIO(xml)).getroot())


class AggregateTest(unittest.TestCase):
    def run_all(self, xmls, known=("28079",)):
        coll = placsp.Collector()
        for x in xmls:
            coll.add_entry(parse(x))
        return coll, placsp.aggregate(coll.records.values(), len(coll.p_ids), set(known), {"entries_read": coll.entries_read})

    def test_totals_quarantine_and_top(self):
        e = entry_xml("e1", "2025-05-01T10:00:00+02:00", results=[
            ("9", "2025-04-01", 1, "1", 1000, GOOD, "Empresa Inventada SL"),
            ("8", "2025-04-02", 3, "2", 500, "12345678Z", "Persona Inventada"),
            ("9", "2024-12-31", 2, "3", 9999, GOOD, "Otra Ficticia SL"),
            ("3", "2025-04-03", 0, "4", 7, GOOD, "Desierto SL"),
        ])
        _, (munis, stats) = self.run_all([e])
        m = munis["28079"]
        self.assertEqual((m["tenders"], m["lots"], m["amount_eur"]), (1, 2, 1500.0))
        self.assertEqual((m["lots_with_offers"], m["lots_single_bid"], m["lots_open"]), (2, 1, 2))
        self.assertEqual(m["by_type"]["works"], {"lots": 2, "amount_eur": 1500.0})
        self.assertEqual(len(m["top"]), 1)
        self.assertEqual(m["top"][0]["winner_nif"], GOOD)
        self.assertEqual(stats["quarantined_lots"], 1)
        self.assertEqual(stats["lots_awarded_other_year_ignored"], 1)
        self.assertEqual(stats["quarantine_share"], 0.5)
        self.assertEqual(stats["result_codes"], {"3": 1, "8": 1, "9": 2})

    def test_quarantined_identity_never_in_output(self):
        e = entry_xml("e1", "2025-05-01T10:00:00+02:00", results=[
            ("9", "2025-04-01", 1, "1", 1000, "12345678Z", "Persona Inventada Unica")])
        _, (munis, stats) = self.run_all([e])
        blob = repr(munis) + repr(stats)
        self.assertNotIn("Persona Inventada", blob)
        self.assertNotIn("12345678Z", blob)
        self.assertEqual(munis["28079"]["top"], [])

    def test_latest_version_wins(self):
        old = entry_xml("e1", "2025-05-01T10:00:00+02:00", results=[("9", "2025-04-01", 1, "1", 100, GOOD, "Vieja SL")])
        new = entry_xml("e1", "2025-06-01T10:00:00+02:00", results=[("9", "2025-04-01", 2, "1", 200, GOOD, "Nueva SL")])
        for order in ((old, new), (new, old)):
            _, (munis, _) = self.run_all(order)
            self.assertEqual(munis["28079"]["amount_eur"], 200.0)

    def test_deleted_entry(self):
        coll = placsp.Collector()
        coll.add_entry(parse(entry_xml("e1", "2025-05-01T10:00:00+02:00", results=[("9", "2025-04-01", 1, "1", 1, GOOD, "X SL")])))
        coll.add_deleted("e1", "2025-06-01T00:00:00+02:00")
        self.assertEqual(len(coll.records), 0)
        self.assertEqual(len(coll.seen) - len(coll.tomb), 0)

    def test_title_with_person_pattern_not_in_top(self):
        e = entry_xml("e1", "2025-05-01T10:00:00+02:00", title="Obra para D. Antonio Falso",
                      results=[("9", "2025-04-01", 1, "1", 1000, GOOD, "Empresa Inventada SL")])
        _, (munis, _) = self.run_all([e])
        self.assertEqual(munis["28079"]["lots"], 1)
        self.assertEqual(munis["28079"]["top"], [])

    def test_unmatched_p_and_unknown_ine_and_non_town_hall(self):
        p = entry_xml("p1", "2025-05-01T10:00:00+02:00", dir3="", nif_body="P0800000A")
        other = entry_xml("o1", "2025-05-01T10:00:00+02:00", dir3="E05024001")
        unk = entry_xml("u1", "2025-05-01T10:00:00+02:00", dir3="L01999990",
                        results=[("9", "2025-04-01", 1, "1", 10, GOOD, "Ficticia SL")])
        coll, (munis, stats) = self.run_all([p, other, unk])
        self.assertEqual(stats["unmatched_p"], 1)
        self.assertEqual(stats["ine_unknown"], ["99999"])
        self.assertEqual(munis, {})
        self.assertEqual(stats["dir3_l01_bodies"], 1)
        self.assertEqual(stats["lots_awarded_2025"], 1)

    def test_cross_platform_duplicate(self):
        a = entry_xml("a", "2025-05-01T10:00:00+02:00", folder="F9", results=[("9", "2025-04-01", 1, "1", 100, GOOD, "A SL")])
        b = entry_xml("b", "2025-06-01T10:00:00+02:00", folder="F9", results=[("9", "2025-04-01", 1, "1", 300, GOOD, "A SL")])
        _, (munis, stats) = self.run_all([a, b])
        self.assertEqual(stats["cross_platform_duplicates"], 1)
        self.assertEqual(munis["28079"]["amount_eur"], 300.0)

    def test_pick_members_spread(self):
        names = [f"{i}.atom" for i in range(100)]
        self.assertEqual(len(placsp.pick_members(names, 10)), 10)
        self.assertEqual(placsp.pick_members(names, 10)[:3], ["0.atom", "10.atom", "20.atom"])
        self.assertEqual(len(placsp.pick_members(names, None)), 100)


if __name__ == "__main__":
    unittest.main()
