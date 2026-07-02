# Seesamin muistitiedostot

Seesamin muisti on vaiheessa 1 tarkoituksella tiedostopohjainen ja käsin muokattava. Tietokantaa tai vektorihakua ei vielä käytetä.

## Paikalliset tiedostot

- `memory/seesam.local.yaml`: Seesamin oma identiteetti, kuten nimi, rooli, kieli, palvelinkone ja backend. Seesamin nimi tulee vain täältä.
- `memory/marko.local.yaml`: käyttäjän profiili ja syvä muisti, kuten nimi, kieli, vastaustyyli ja pysyvät mieltymykset.
- `memory/memories.local.txt`: tavalliset `muista tämä` -muistot muodossa `M000001 | aikaleima | source=... | teksti`.
- `memory/episodes.local.log`: aikaleimattu tapahtumaloki käyttäjän viesteistä ja muistitoiminnoista.

Vanhaa `memory/marko.local.txt` -tiedostoa ei enää käytetä käyttäjäprofiilina. Vanhan tiedoston M000001-rivit siirretään tavallisiin muistoihin ja profiilirivit Markon YAML-profiiliin.

## Git

Gitiin saa lisätä vain esimerkkitiedostot ja dokumentaation:

- `memory/seesam.example.yaml`
- `memory/marko.example.yaml`
- `memory/memories.example.txt`
- `MEMORY.md`

Älä committoi paikallisia muisteja tai ympäristöasetuksia: `memory/*.local.yaml`, `memory/*.local.txt`, `memory/*.local.json`, `memory/*.local.log`, `.env` tai `*.log`.

## Komennot

- `muista tämä: ...` tallentaa tavallisen muiston `memories.local.txt`-tiedostoon.
- `tallenna syvään muistiin: ...` tallentaa pysyvämmän käyttäjätiedon `marko.local.yaml`-tiedoston `deep_memory`-listaan.
- `mitä muistat` näyttää ensin käyttäjän syvän muistin ja sitten tavalliset muistot.
- `näytä viimeisimmät muistot` näyttää viimeisimmät tavalliset muistot numeroituna.
- `mikä on viimeisin muistosi` näyttää viimeisimmän tavallisen muiston.
- `poista viimeisin muistosi`, `poista viimeisin muisto`, `peru viimeisin muisto` ja `unohda viimeisin muisto` poistavat viimeisimmän tavallisen muiston.
- `poista muisto numero X` poistaa numeron viimeisimpien muistojen listalta.
