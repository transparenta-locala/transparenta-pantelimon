# API public — Transparența Pantelimon

Datele generate automat de `monitor_pantelimon.py` sunt disponibile public ca endpoint JSON.
Actualizate lunar (de obicei pe 15 ale lunii).

**Licență:** Creative Commons CC-BY 4.0 — atribuire obligatorie: „Transparența Pantelimon / transparenta-pantelimon.eu"

---

## Endpoint: `raport.json`

**URL:** `https://transparenta-pantelimon.eu/raport.json`

Raportul complet cu toate semnalele automate, totaluri și indicele euristic de transparență.

### Schema

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-05-15T14:32:10.123456",
  "entity": {
    "name": "Primăria Pantelimon",
    "cif": "4420759",
    "judet": "Ilfov"
  },
  "totals": {
    "flags": 299,
    "contracts_analyzed": 506,
    "total_value_ron": 313680510.12,
    "by_severity": {
      "CRITIC": 107,
      "MAJOR": 55,
      "MEDIU": 137
    }
  },
  "flags": [
    {
      "id": 1,
      "severity": "CRITIC",
      "title": "Achiziție directă peste pragul legal",
      "explanation": "Descriere detaliată cu baza legală.",
      "supplier": "MIDAS ROAD S.R.L.",
      "sum_ron": 880000.0,
      "date": "2024-04-03",
      "contract_id": "achizitie-directa-2024-489392",
      "procedure": "Achizitie directa",
      "type": "ACHIZITIE_DIRECTA_PESTE_PRAG",
      "anchor": "nereguli-1"
    }
  ],
  "scor_transparenta": {
    "scor": 47,
    "componente": {
      "achizitii_directe": 55,
      "ofertant_unic": 40,
      "sedinte_extraordinare": 70,
      "fragmentare": 60,
      "documente": 50
    }
  }
}
```

### Câmpuri flag

| Câmp | Tip | Descriere |
|---|---|---|
| `id` | integer | Index 1-based în ordinea sortată (CRITIC → MAJOR → MEDIU) |
| `severity` | string | `CRITIC`, `MAJOR` sau `MEDIU` |
| `title` | string | Titlu scurt al semnalului |
| `explanation` | string | Descriere detaliată cu baza legală (max ~500 caractere) |
| `supplier` | string | Denumire firmă furnizor (dacă e aplicabil) |
| `sum_ron` | number | Valoare contract în RON |
| `date` | string | Data contractului (format `YYYY-MM-DD`) |
| `contract_id` | string | ID contract SEAP (ex: `achizitie-directa-2024-489392`) |
| `procedure` | string | Tipul procedurii (`Achizitie directa`, `Licitatie deschisa` etc.) |
| `type` | string | Codul intern al tipului de nereguă (vezi mai jos) |
| `anchor` | string | ID-ul HTML al cardului în raport (`nereguli-N`) |

### Tipuri de semnale (`type`)

| Cod | Severitate tipică | Descriere |
|---|---|---|
| `ACHIZITIE_DIRECTA_PRAG` | MEDIU | Achiziție directă >97% din prag (126.100 RON) |
| `ACHIZITIE_DIRECTA_PESTE_PRAG` | CRITIC | Achiziție directă individuală peste 270.120 RON produse/servicii sau 900.400 RON lucrări, fără TVA |
| `OFERTANT_UNIC` | MEDIU/MAJOR | Un singur ofertant — lipsă concurență reală |
| `FRAGMENTARE` | CRITIC | Fragmentare artificială pentru eludarea pragului |
| `FRAGMENTARE_TEMPORARA` | CRITIC | Contracte similare consecutive sub prag (L98/2016 art.11) |
| `CONCENTRARE_FURNIZOR` | MAJOR/CRITIC | Top 3 furnizori dețin >60% din valoarea totală |
| `CONTRACTE_CONSECUTIVE` | MAJOR | Același furnizor, ≥4 contracte în 30 de zile |
| `SEDINTE_EXTRAORDINARE_EXCESIVE` | MAJOR/CRITIC | Rata ședințelor extraordinare >25% din total |
| `PUBLICARE_INTARZIATA` | MEDIU/CRITIC | Publicare SEAP la >11 zile lucrătoare de la atribuire |
| `VALORI_IDENTICE_ACEEASI_ZI` | CRITIC | Valori identice atribuite la firme diferite în aceeași zi |
| `BURST_CONTRACTE` | MEDIU/MAJOR | Volum anormal de contracte într-o singură zi |
| `SEMNARE_ZILE_NELUCRATOARE` | MEDIU | Contract semnat în weekend sau sărbătoare legală |

---

## Endpoint: `contracte.json`

**URL:** `https://transparenta-pantelimon.eu/contracte.json`

Lista tuturor contractelor analizate (sursa: SEAP).

### Schema

```json
[
  {
    "id": "achizitie-directa-2025-2637",
    "titlu": "Publicatii periodice",
    "valoare": 66000.0,
    "data": "2025-01-08",
    "tip": "Achizitie directa",
    "firma": "ASOCIATIA CENTRUL ROMAN...",
    "cui": "12345678",
    "ofertanti": 1
  }
]
```

---

## Endpoint: `feed.xml`

**URL:** `https://transparenta-pantelimon.eu/feed.xml`

Feed Atom cu top 20 semnale (compatibil RSS). Util pentru Feedly, Inoreader etc.

---

## Endpoint: `contracte.csv`

**URL:** `https://transparenta-pantelimon.eu/contracte.csv`

Același dataset ca `contracte.json` în format CSV — compatibil Excel, Google Sheets, pandas.

### Schema (coloane)

| Coloană | Tip | Descriere |
|---|---|---|
| `id` | string | ID contract SEAP (ex: `achizitie-directa-2025-2637`) |
| `titlu` | string | Obiectul contractului (max 80 caractere) |
| `valoare` | number | Valoarea contractului în RON |
| `data` | string | Data atribuirii (`YYYY-MM-DD`) |
| `tip` | string | Tipul procedurii (ex: `Achizitie directa`) |
| `firma` | string | Denumirea câștigătorului |
| `cui` | string | CUI/CIF furnizor |
| `ofertanti` | integer | Numărul de ofertanți (0 = necunoscut) |

---

## Endpoint: `press_kit.json`

**URL:** `https://transparenta-pantelimon.eu/press_kit.json`

Press kit auto-generat cu statistici și top semnale — destinat jurnaliștilor.

### Schema

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-05-15T14:32:10",
  "statistici": {
    "total_flags": 299,
    "critic": 107,
    "major": 55,
    "mediu": 137,
    "total_contracte": 506,
    "valoare_totala_ron": 313680510.12,
    "scor_transparenta": 47
  },
  "top_nereguli": [
    {
      "titlu": "Achiziție directă peste pragul legal",
      "severitate": "CRITIC",
      "furnizor": "MIDAS ROAD S.R.L.",
      "valoare": 880000.0
    }
  ],
  "top_firme": [
    {
      "firma": "MIDAS ROAD S.R.L.",
      "valoare_totala": 4320000.0,
      "nr_contracte": 7,
      "cui": "RO12345678"
    }
  ]
}
```

---

## Endpoint: `pnrr_projects.json`

**URL:** `https://transparenta-pantelimon.eu/pnrr_projects.json`

Proiectele PNRR cu beneficiar Primăria Pantelimon (sursă: `proiecte.pnrr.gov.ro`).
Cache TTL: 7 zile.

### Schema (array de obiecte)

| Câmp | Tip | Descriere |
|---|---|---|
| `titlu` | string | Denumirea proiectului |
| `cod` | string | Codul proiectului PNRR |
| `valoare_ron` | number | Valoarea totală în RON |
| `status` | string | Stadiul proiectului |
| `program` | string | Programul de finanțare (ex: PNRR, POR) |
| `beneficiar` | string | Denumirea beneficiarului |
| `link` | string | URL pagina proiectului |
| `extras_la` | string | Data extragerii (`YYYY-MM-DD`) |

---

## Endpoint: `ani_declaratii.json`

**URL:** `https://transparenta-pantelimon.eu/ani_declaratii.json`

Declarații de avere și interese ale aleșilor locali din Pantelimon (sursă: ANI / integritate.eu).
Cache TTL: 30 zile.

### Schema (array de obiecte)

| Câmp | Tip | Descriere |
|---|---|---|
| `nume` | string | Numele persoanei publice |
| `functie` | string | Funcția deținută |
| `an` | string | Anul declarației |
| `tip` | string | `avere` sau `interese` |
| `url_pdf` | string | Link PDF declarație pe integritate.eu |
| `extras_la` | string | Data extragerii |

---

## Endpoint: `curtea_de_conturi.json`

**URL:** `https://transparenta-pantelimon.eu/curtea_de_conturi.json`

Rapoarte de audit ale Curții de Conturi pentru UAT Pantelimon (sursă: curteadeconturi.ro).
Cache TTL: 30 zile.

### Schema (array de obiecte)

| Câmp | Tip | Descriere |
|---|---|---|
| `titlu` | string | Titlul raportului de audit |
| `an` | string | Anul auditului |
| `url` | string | Link PDF raport |
| `tip` | string | Tipul controlului (ex: `audit financiar`) |
| `extras_la` | string | Data extragerii |

---

## Endpoint: `ted_notices.json`

**URL:** `https://transparenta-pantelimon.eu/ted_notices.json`

Anunțuri de achiziție publică din Jurnalul Oficial al UE (TED Europa) asociate cumpărătorului cu CIF 4420759.
Pentru 2026–2027, pragurile Directivei 2014/24/UE sunt 216.000 EUR fără TVA pentru produse/servicii atribuite de autorități locale și 5.404.000 EUR fără TVA pentru lucrări. Absența unui rezultat din acest export nu dovedește singură nerespectarea unei obligații de publicare.
Cache TTL: 7 zile.

### Schema (array de obiecte)

| Câmp | Tip | Descriere |
|---|---|---|
| `notice_id` | string | ID anunț TED |
| `title` | string | Titlul anunțului |
| `publication_date` | string | Data publicării (`YYYY-MM-DD`) |
| `value_eur` | number | Valoarea în EUR (dacă disponibil) |
| `url` | string | Link anunț pe ted.europa.eu |
| `extras_la` | string | Data extragerii |

---

## Endpoint: `mol_primarie.json`

**URL:** `https://transparenta-pantelimon.eu/mol_primarie.json`

Hotărâri din Monitorul Oficial Local al Primăriei Pantelimon (sursă: primariapantelimon.ro).
Cache TTL: 7 zile.

### Schema (array de obiecte)

| Câmp | Tip | Descriere |
|---|---|---|
| `titlu` | string | Titlul hotărârii (HCL) |
| `numar` | string | Numărul hotărârii |
| `data` | string | Data adoptării |
| `url` | string | Link document |
| `tip` | string | Tipul documentului |
| `extras_la` | string | Data extragerii |

---

## Endpoint: `firme_geocoded.json`

**URL:** `https://transparenta-pantelimon.eu/firme_geocoded.json`

Coordonatele geografice ale sediilor furnizorilor cu contracte la Primăria Pantelimon.
Geocodare via Nominatim/OpenStreetMap. Cache TTL: 180 zile.
Folosit de harta.html (Leaflet.js).

### Schema (array de obiecte)

| Câmp | Tip | Descriere |
|---|---|---|
| `cui` | string | CUI/CIF furnizor |
| `name` | string | Denumirea firmei |
| `address` | string | Adresa sediului social |
| `lat` | number | Latitudine (null dacă geocodarea a eșuat) |
| `lng` | number | Longitudine (null dacă geocodarea a eșuat) |
| `valoare` | number | Valoarea totală contracte în RON |
| `nr_contracte` | integer | Numărul de contracte cu primăria |

---

## Utilizare responsabilă

- Respectă limitele serverului (max 1 req/minut dacă faci poll automat)
- Citează sursa: „Date: Transparența Pantelimon / transparenta-pantelimon.eu, CC-BY 4.0"
- Datele SEAP au decalaj de 1-3 luni față de realitate
- Semnalele sunt indicatori euristici, pot avea suprapuneri și nu sunt concluzii juridice sau prejudicii

## Contact

Probleme cu schema sau lipsă date: [GitHub Issues](https://github.com/transparenta-locala/transparenta-pantelimon/issues)
