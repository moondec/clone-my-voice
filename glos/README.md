# Profile głosu

Ten katalog przechowuje próbki referencyjne głosu (`*.wav`) — tzw. **profile**.

Pliki audio są **celowo poza repozytorium** (patrz `.gitignore`) ze względów
prywatności — nikt nie klonuje Twojego głosu z publicznego repo. Po sklonowaniu
projektu katalog jest pusty; dodaj własną próbkę:

```bash
./przygotuj_glos.sh /sciezka/do/nagrania.m4a    # tworzy glos/Marek_ref.wav
```

albo przez GUI: `./serwuj` → panel „Nagraj nową próbkę".

Najlepsza próbka: **15–30 s** czystej, spokojnej mowy — bez szumu, muzyki i pogłosu.
Każdy plik `glos/<nazwa>.wav` to osobny profil wybierany w narzędziu (`-g`) lub w GUI.
