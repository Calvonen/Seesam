# Seesam

Seesam on Markon paikallinen terminaaliavustaja. Keskustelu tapahtuu
terminaalissa, ja varsinaiset vastaukset haetaan paikalliselta Ollama-palvelulta.

## Vaatimukset

- Python 3.12+
- Docker Compose, jos haluat ajaa avustajan kontissa
- Ollama käynnissä koneella
- Ollama-malli `gemma3:1b`
- Python-virtuaaliympäristö projektin hakemistossa (`.venv`)

Lataa oletusmalli:

```sh
ollama pull gemma3:1b
```

## Python-virtuaaliympäristö

Luo projektin paikallinen virtuaaliympäristö ennen riippuvuuksien asentamista
ja komentojen ajamista:

```sh
python3 -m venv .venv
```

Aktivoi virtuaaliympäristö macOS- tai Linux-terminaalissa:

```sh
source .venv/bin/activate
```

Aktivoi virtuaaliympäristö Windows PowerShellissä:

```powershell
.venv\Scripts\Activate.ps1
```

Asenna Python-riippuvuudet aktivoidun virtuaaliympäristön sisään:

```sh
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Kun virtuaaliympäristö on aktiivinen, kaikki `python`- ja `python -m ...`
-komennot käyttävät projektin `.venv`-ympäristöä. Jos avaat uuden terminaalin,
aktivoi `.venv` uudelleen ennen Seesamin ajamista, API:n käynnistämistä tai
testien suorittamista.

## Asetukset

Kopioi esimerkkiasetukset omaan `.env`-tiedostoon:

```sh
cp .env.example .env
```

Oletusarvot ovat:

```env
OLLAMA_MODEL=gemma3:1b
OLLAMA_HOST=http://127.0.0.1:11434
TTS_ENABLED=true
TTS_ENGINE=piper
TTS_PIPER_BIN=piper
TTS_MODEL=/home/marko/piper-models/fi_FI-harri-medium.onnx
```

## Ajaminen paikallisesti

Aktivoi ensin virtuaaliympäristö ja käynnistä terminaalichat:

```sh
source .venv/bin/activate
python -m core.main
```

Kirjoita viesti kehotteeseen `Marko:`. Paikallinen komento `seesam aukene`
vastaa heti `Seesam: Kuuntelen.` ilman Ollama-kutsua. Muut viestit, kuten
`moro`, lähetetään Ollamalle Seesamin suomalaisella persoonallisuudella.

Lopeta komennolla `exit`, `quit`, `lopeta` tai näppäinyhdistelmällä Ctrl-D.


## HTTP API

Seesam sisältää myös FastAPI-pohjaisen HTTP-rajapinnan. Asenna ensin
riippuvuudet virtuaaliympäristöön kohdan "Python-virtuaaliympäristö" mukaisesti.

Käynnistä API paikallisesti aktivoidussa virtuaaliympäristössä:

```sh
source .venv/bin/activate
python -m uvicorn core.api:app --host 127.0.0.1 --port 8000
```

Tarkista palvelun tila:

```sh
curl http://127.0.0.1:8000/health
```

Lähetä chat-viesti:

```sh
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"moro"}'
```

Vastaus palautetaan muodossa `{"answer":"..."}`. API käyttää samaa
`Brain`-luokkaa kuin terminaalichat, joten paikalliset komennot, muisti,
persoonallisuus ja Ollama-asetukset toimivat samalla tavalla molemmissa
käyttötavoissa. Terminaalichat toimii edelleen aktivoidussa virtuaaliympäristössä komennolla `python -m core.main`.

## Paikallinen muisti

Seesam lukee ja kirjoittaa Markon paikalliset muistot oletuksena tiedostoon
`memory/marko.local.txt`. Tiedosto on yksityinen paikallinen muisti, eikä sitä
commitoida Git-repositorioon. Tiedoston ei tarvitse olla olemassa etukäteen:
Seesam luo sen ja `memory`-hakemiston ensimmäisen tallennuksen yhteydessä.

Muistin muoto on yksinkertainen: yksi muisto per rivi. Repositorion mukana
tuleva `memory/marko.example.txt` on vain esimerkkitiedosto muistin muodosta.
Voit halutessasi kopioida siitä lähtökohdan omaan paikalliseen muistiin:

```sh
cp memory/marko.example.txt memory/marko.local.txt
```

## Piper-puhe

Seesam voi lukea vastaukset ääneen Piperillä. Asenna Piper niin, että komento
`piper` löytyy terminaalista, ja varmista että `aplay` toimii äänen toistoon.
Lataa tai sijoita suomalainen äänimalli paikallisesti, esimerkiksi:

```sh
/home/marko/piper-models/fi_FI-harri-medium.onnx
```

Ota puhe käyttöön `.env`-tiedostossa:

```env
TTS_ENABLED=true
TTS_ENGINE=piper
TTS_PIPER_BIN=piper
TTS_MODEL=/home/marko/piper-models/fi_FI-harri-medium.onnx
```

Jos Piper on asennettu tämän projektin virtuaaliympäristöön, aseta
`TTS_PIPER_BIN` osoittamaan suoraan `.venv`-binääriin, esimerkiksi:

```env
TTS_PIPER_BIN=/home/marko/Seesam/.venv/bin/piper
```

Jos Piper, mallitiedosto tai `aplay` ei ole käytettävissä, Seesam jatkaa
terminaalichattia normaalisti ilman kaatumista.

## Ajaminen Docker Composella

Käynnistä terminaalichat kontissa:

```sh
docker compose run --rm seesam-core
```

Jos Ollama pyörii isäntäkoneella, varmista että `OLLAMA_HOST` osoittaa kontista
saavutettavaan osoitteeseen. Linuxissa voit tarvita esimerkiksi host-verkon tai
oman osoitteen ympäristömuuttujaan.

## Testit

Suorita testit aktivoidussa virtuaaliympäristössä:

```sh
source .venv/bin/activate
python -m pytest
```
