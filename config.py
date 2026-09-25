"""
config.py — TTL-uri cache centralizate per sursă de date
==========================================================

Un singur loc pentru toate duratele de valabilitate (TTL) ale cache-urilor
folosite de scripturile de monitorizare. Fiecare valoare e aleasă pe baza
cadenței reale de publicare a sursei — vezi CLAUDE.md secțiunea
"Cache TTL policy" pentru justificarea completă per sursă.

Import: `from config import TTL_MOL_DAYS` etc.
"""

# Legea nr. 98/2016, art. 7 alin. (5): praguri pentru achiziții directe,
# exprimate în lei fără TVA. O singură definiție previne diferențe între
# detectori, paginile publice și teste.
PRAG_ACHIZITIE_DIRECTA_PRODUSE_SERVICII_RON = 270_120
PRAG_ACHIZITIE_DIRECTA_LUCRARI_RON = 900_400
PRAGURI_LEGALE_VERIFICATE_LA = "2026-07-13"
PRAGURI_LEGALE_SURSA = "https://legislatie.just.ro/Public/DetaliiDocument/178667"

# mfinante.gov.ro — situații financiare firme furnizoare (risc_firma.py).
# Publicate anual; TTL istoric păstrat neschimbat.
TTL_MFINANTE_DAYS = 30

# data.gov.ro — export SEAP contracte (trimestrial) + pagina HCL primărie.
# Fișiere XLSX mari (10-50MB); refresh săptămânal evită re-descărcarea
# aceluiași export la fiecare rulare zilnică.
TTL_SEAP_CONTRACTE_DAYS = 7
TTL_HCL_DAYS = 7

# curteadeconturi.ro — rapoarte de audit UAT, publicate de regulă anual.
TTL_CURTEA_CONTURI_DAYS = 90

# integritate.eu (ANI) — declarații de avere/interese, actualizate anual.
TTL_ANI_DAYS = 30

# TED Europa — anunțuri achiziții publice mari (>500k EUR), publicate zilnic.
TTL_TED_DAYS = 7

# Monitorul Oficial Local (MOL) primărie — rectificări bugetare + HCL,
# publicate la fiecare ședință a Consiliului Local (cadență ~bilunară).
TTL_MOL_DAYS = 14

# PNRR — proiecte finanțate din fonduri europene, actualizate ocazional.
TTL_PNRR_DAYS = 7

# ONRC / data.gov.ro (OD_FIRME.CSV, OD_REPREZENTANTI_LEGALI.CSV) —
# administratori/reprezentanți legali firme, se schimbă rar.
TTL_ONRC_DAYS = 30

# Nominatim / OpenStreetMap — coordonate geografice adrese firme. Sediile
# fiscale se schimbă foarte rar.
TTL_NOMINATIM_DAYS = 365

# ANAF v9 — stare înregistrare TVA / dată înființare firmă. Se schimbă rar
# (radiere, suspendare) — cache lung pentru a nu suprasolicita API-ul gratuit.
TTL_ANAF_V9_DAYS = 365

# data.gov.ro — situații financiare ANAF (WEB_BL/WEB_UU), publicate anual
# (mai-iulie). Pragul e citit din acest modul de
# .github/workflows/update-report.yml pentru a rămâne sincronizat.
TTL_FIRME_FINANCIAR_REFRESH_DAYS = 365

# Google News + Context.ro — mențiuni presă firme furnizoare, conținut dinamic.
TTL_PRESA_DAYS = 7
