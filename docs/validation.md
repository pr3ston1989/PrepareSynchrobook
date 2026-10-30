# Walidacja 0.1.0 — 2026-10-30

## Automatyczne

- 16 testów narzędzia: paczka zawiera wyłącznie manifest, hash oryginalnego EPUB, różne podziały EPUB/audio, cisza między plikami, polskie znaki i UTF-16/emoji, brak fikcyjnych kotwic dla obcego tekstu, nieprawidłowe czasy, naturalna kolejność, cache i wznowienie przerwanego rozpoznawania, zmiana pliku/modelu, obsługa sesji i przekierowań klienta API.
- 35 testów Nokturna w `web/backend/tests/test_synchrobook_import.py`: zgodność paczki z oddzielnego repozytorium i prawdziwym parserem czytnika, kontrola źródeł, uprawnienia administratora, pobranie EPUB, idempotencja, odrzucanie uszkodzonych paczek, integralność po odmowie, konflikt z rozpoznawaniem lokalnym, zachowanie postępu oraz unieważnienie kotwic po zmianie EPUB/pliku audio.
- Regresja backendu Nokturna: końcowy pełny przebieg 686 testów zaliczonych i 6 podtestów; po dodaniu testu konsolowego zarządzania kluczami osobny zestaw importu i uprawnień: 35/35.

## Rzeczywiste rozpoznawanie i API

Na Windows/Python 3.13 wygenerowano lokalnym SAPI Paulina dwa polskie nagrania z własnego tekstu o kotach. Dodano ciszę przed i po mowie, zapisano MP3 przez PyAV. Oddzielny EPUB zawierał tekst książki i dodatkową stronę tytułową; miał trzy rozdziały, a nagranie dwa pliki.

Model `small`, CPU/INT8/VAD i znaczniki słów: **5/5 akapitów treści dopasowanych**, 2 akapity strony tytułowej niedopasowane, pokrycie całego EPUB 92%. Czasy uwzględniały pełną długość pierwszego MP3 (33,33 s). To test funkcjonalny krótkiego materiału; nie oznacza 92% lub 100% dokładności na dowolnym audiobooku.

Na osobnym lokalnym serwerze Nokturna przetestowano rzeczywiste połączenie klienta: klucz API administratora → wyszukanie własnego testowego tytułu → pobranie oryginalnego EPUB → import paczki → odczyt pięciu znaczników przez standardowe API czytnika. EPUB był identyczny bajtowo przed i po imporcie, podobnie wszystkie wiersze postępu audio. Dodatkowo klucz API nie uzyskał dostępu do konta, a po odwołaniu natychmiast otrzymał 401. Nie importowano niczego do rzeczywistej biblioteki użytkownika.

Rzeczywisty test ujawnił niezgodność API `faster-whisper 1.2.1` z PyAV 19. Zależność przypięto do sprawdzonego `av==16.1.0` i test rozpoznawania powtórzono pomyślnie.

## Windows i interfejs

- Czyste przygotowanie środowiska przez `tools/start.ps1 -SetupOnly` w Windows PowerShell 5.1: zaliczone.
- Podgląd rzeczywistego okna: tabela dopasowań, zestawienie tekstu EPUB i rozpoznanej mowy, tworzenie paczki z przycisku i przejście do połączenia z Nokturnem. Formularze mają przewijanie, a pasek wyniku pozostaje widoczny.
- Wygląd sprawdzono przy 1000 × 780. Nie deklarujemy walidacji wszystkich skal DPI, rozdzielczości, kart GPU ani kilkunastogodzinnego audiobooka w tej pierwszej wersji.

Do powtarzania podstawowej regresji: `python -m unittest discover -s tests -v`. Testy nie wysyłają wiadomości e-mail ani nie korzystają z produkcyjnych kont i bibliotek.
