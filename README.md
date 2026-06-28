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
