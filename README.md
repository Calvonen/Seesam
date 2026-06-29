# Seesam

Seesam on Markon paikallinen terminaaliavustaja. Keskustelu tapahtuu
terminaalissa, ja varsinaiset vastaukset haetaan paikalliselta Ollama-palvelulta.

## Vaatimukset

- Python 3.12+
- Docker Compose, jos haluat ajaa avustajan kontissa
- Ollama käynnissä koneella
- Ollama-malli `gemma3:1b`

Lataa oletusmalli:

```sh
ollama pull gemma3:1b
```

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

Käynnistä terminaalichat:

```sh
python -m core.main
```

Kirjoita viesti kehotteeseen `Marko:`. Paikallinen komento `seesam aukene`
vastaa heti `Seesam: Kuuntelen.` ilman Ollama-kutsua. Muut viestit, kuten
`moro`, lähetetään Ollamalle Seesamin suomalaisella persoonallisuudella.

Lopeta komennolla `exit`, `quit`, `lopeta` tai näppäinyhdistelmällä Ctrl-D.

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

Jos Piper on asennettu virtuaaliympäristöön, aseta `TTS_PIPER_BIN` osoittamaan
suoraan binääriin, esimerkiksi:

```env
TTS_PIPER_BIN=/home/marko/piper-venv/bin/piper
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

```sh
python -m pytest
```
