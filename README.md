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
TTS_MODEL=/path/to/piper-model.onnx
STT_ENABLED=true
STT_ENGINE=faster-whisper
STT_MODEL=small
STT_LANGUAGE=fi
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
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

Hae palvelimen laitteisto- ja käyttöjärjestelmätiedot:

```sh
curl http://127.0.0.1:8000/system/specs
```

Vastaus sisältää palvelimen `hostname`-, `os_name`-, `kernel`-, CPU-, RAM-, levy-
ja `local_ip`-tiedot. Jos `nvidia-smi` löytyy ja GPU on käytettävissä, mukana on
myös `gpu_name`; GPU:n puuttuminen ei tee pyynnöstä virhettä.

Lähetä chat-viesti:

```sh
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"moro"}'
```

Vastaus palautetaan muodossa `{"answer":"..."}`. API käyttää samaa
`Brain`-luokkaa kuin terminaalichat, joten paikalliset komennot, muisti,
persoonallisuus ja Ollama-asetukset toimivat samalla tavalla molemmissa
käyttötavoissa.

Luo puhe WAV-tiedostona Piper-asetuksilla:

```sh
curl -X POST http://127.0.0.1:8000/speak \
  -H "Content-Type: application/json" \
  -d '{"text":"moro Marko"}' \
  --output seesam.wav
```

Endpoint palauttaa `audio/wav`-vastauksen eikä toista ääntä palvelimella. Jos
TTS ei ole käytössä tai Piperin binääri tai mallitiedosto puuttuu, vastaus on
JSON-muotoinen virhe sopivalla HTTP-tilakoodilla.

Litteroi sovelluksen lähettämä äänitiedosto tekstiksi:

```sh
curl -X POST http://127.0.0.1:8000/transcribe \
  -F "file=@seesam.wav;type=audio/wav"
```

Vastaus palautetaan muodossa `{"text":"..."}`. Oletuskieli on suomi
`STT_LANGUAGE=fi`-asetuksella, ja oletusmoottori on paikallinen
`faster-whisper`. Jos STT ei ole käytössä, `faster-whisper` puuttuu tai
Whisper-mallia ei saada ladattua, endpoint palauttaa JSON-muotoisen virheen
sopivalla HTTP-tilakoodilla. Terminaalichat toimii edelleen
aktivoidussa virtuaaliympäristössä komennolla `python -m core.main`.

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

Seesam voi lukea vastaukset ääneen Piperillä ja `/speak` voi palauttaa puheen
WAV-tiedostona. Asenna Piper niin, että komento `piper` löytyy `PATH`-polusta,
tai aseta `TTS_PIPER_BIN` osoittamaan Piperin suoritettavaan tiedostoon.

Lataa Piperin `.onnx`-äänimalli paikalliseen hakemistoon. Esimerkiksi
suomenkielisen äänen voi sijoittaa projektin ulkopuolelle omaan mallihakemistoon,
ja `TTS_MODEL` asetetaan osoittamaan siihen tiedostoon.

Ota puhe käyttöön `.env`-tiedostossa:

```env
TTS_ENABLED=true
TTS_ENGINE=piper
TTS_PIPER_BIN=piper
TTS_MODEL=/path/to/piper-model.onnx
```

Jos Piper on asennettu tämän projektin virtuaaliympäristöön, voit käyttää
suhteellista projektipolkua tai absoluuttista polkua, esimerkiksi:

```env
TTS_PIPER_BIN=.venv/bin/piper
```

`/speak` palauttaa JSON-virheen, jos TTS on pois käytöstä, Piper-binääriä ei
löydy, mallitiedosto puuttuu tai Piper ei pysty luomaan WAV-tiedostoa.
Terminaalichat jatkaa edelleen normaalisti ilman kaatumista, jos Piper,
mallitiedosto tai `aplay` ei ole käytettävissä.

## Whisper-litterointi

`/transcribe` käyttää `faster-whisper`-kirjastoa paikalliseen
puheentunnistukseen. Oletusasetukset ovat:

```env
STT_ENABLED=true
STT_ENGINE=faster-whisper
STT_MODEL=small
STT_LANGUAGE=fi
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
```

`STT_MODEL` voi olla faster-whisperin mallinimi kuten `small` tai polku
paikalliseen mallihakemistoon. Oletuksena litterointi käyttää CPU:ta asetuksilla
`STT_DEVICE=cpu` ja `STT_COMPUTE_TYPE=int8`, jotta CUDA-kirjastoja ei tarvita.
GPU:n voi ottaa myöhemmin käyttöön asetuksilla `STT_DEVICE=cuda` ja
`STT_COMPUTE_TYPE=float16`. Ensimmäinen mallinimen käyttö voi vaatia mallin
lataamisen faster-whisperin välimuistiin. Jos STT on pois käytöstä tai mallia
ei saada ladattua, `/transcribe` palauttaa selkeän JSON-virheen.

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
