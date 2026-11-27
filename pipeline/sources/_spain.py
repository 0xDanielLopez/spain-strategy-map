"""Spanish administrative constants: the 19 autonomous communities (CCAA) and the province -> CCAA map."""

# code = INE autonomous community code; nuts2 = Eurostat NUTS 2 code; iso = ISO 3166-2 suffix.
CCAA = [
    {"code": "01", "nuts2": "ES61", "iso": "AN", "name": "Andalucía"},
    {"code": "02", "nuts2": "ES24", "iso": "AR", "name": "Aragón"},
    {"code": "03", "nuts2": "ES12", "iso": "AS", "name": "Principado de Asturias"},
    {"code": "04", "nuts2": "ES53", "iso": "IB", "name": "Illes Balears"},
    {"code": "05", "nuts2": "ES70", "iso": "CN", "name": "Canarias"},
    {"code": "06", "nuts2": "ES13", "iso": "CB", "name": "Cantabria"},
    {"code": "07", "nuts2": "ES41", "iso": "CL", "name": "Castilla y León"},
    {"code": "08", "nuts2": "ES42", "iso": "CM", "name": "Castilla-La Mancha"},
    {"code": "09", "nuts2": "ES51", "iso": "CT", "name": "Cataluña"},
    {"code": "10", "nuts2": "ES52", "iso": "VC", "name": "Comunitat Valenciana"},
    {"code": "11", "nuts2": "ES43", "iso": "EX", "name": "Extremadura"},
    {"code": "12", "nuts2": "ES11", "iso": "GA", "name": "Galicia"},
    {"code": "13", "nuts2": "ES30", "iso": "MD", "name": "Comunidad de Madrid"},
    {"code": "14", "nuts2": "ES62", "iso": "MC", "name": "Región de Murcia"},
    {"code": "15", "nuts2": "ES22", "iso": "NC", "name": "Comunidad Foral de Navarra"},
    {"code": "16", "nuts2": "ES21", "iso": "PV", "name": "País Vasco"},
    {"code": "17", "nuts2": "ES23", "iso": "RI", "name": "La Rioja"},
    {"code": "18", "nuts2": "ES63", "iso": "CE", "name": "Ceuta"},
    {"code": "19", "nuts2": "ES64", "iso": "ML", "name": "Melilla"},
]

# INE province code -> CCAA code (52 provinces, including Ceuta and Melilla).
PROVINCE_TO_CCAA = {
    "01": "16", "02": "08", "03": "10", "04": "01", "05": "07", "06": "11", "07": "04", "08": "09",
    "09": "07", "10": "11", "11": "01", "12": "10", "13": "08", "14": "01", "15": "12", "16": "08",
    "17": "09", "18": "01", "19": "08", "20": "16", "21": "01", "22": "02", "23": "01", "24": "07",
    "25": "09", "26": "17", "27": "12", "28": "13", "29": "01", "30": "14", "31": "15", "32": "12",
    "33": "03", "34": "07", "35": "05", "36": "12", "37": "07", "38": "05", "39": "06", "40": "07",
    "41": "01", "42": "07", "43": "09", "44": "02", "45": "08", "46": "10", "47": "07", "48": "16",
    "49": "07", "50": "02", "51": "18", "52": "19",
}
