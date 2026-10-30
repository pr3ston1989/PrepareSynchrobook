# PrepareSynchrobook

Zewnętrzne narzędzie Windows do przygotowywania synchronizacji dla [Nokturna](https://github.com/pr3ston1989/audiobook_parser).

**Prawdziwy EPUB pozostaje tekstem książki.** Transkrypcja nagrania jest wyłącznie materiałem do wyszukania odpowiadających sobie miejsc. Program rozpoznaje słowa lokalnie, dopasowuje je do oryginalnego EPUB i przesyła przez API same znaczniki synchronizacji. Pozwala to Nokturnowi odnajdywać miejsce audio w tekście i miejsce tekstu w nagraniu.

## Uruchomienie

1. Zainstaluj **64-bit Python 3.10–3.13** z [python.org](https://www.python.org/downloads/windows/), z Tcl/Tk. Środowisko wydania sprawdzono na Windows i Pythonie 3.13. Nie potrzeba osobnego FFmpeg.
2. Rozpakuj ZIP do stałego folderu, np. `C:\PrepareSynchrobook`.
3. Uruchom `Start_PrepareSynchrobook.bat`. Pierwszy start przygotuje osobne środowisko i pobierze zależności.
4. Opcjonalnie uruchom `Zainstaluj_skrot_na_pulpicie.bat`. Zachowaj rozpakowany folder programu — skrót odwołuje się do niego.

Środowisko programu znajduje się w `%LOCALAPPDATA%\PrepareSynchrobook\runtime`. Modele korzystają ze standardowej pamięci Hugging Face użytkownika. Pierwsze pobranie modelu wymaga internetu. Rozpoznawanie później może działać offline; przesyłanie wymaga połączenia z Nokturnem.

## Przepływ pracy

1. W Nokturnie audiobook powinien mieć przypisany **właściwy EPUB**. Zaktualizowany serwer musi udostępniać `/api/synchrobooks/capabilities` (schema 1, `existing_epub_only=true`).
2. Na komputerze serwera uruchom `C:\Nokturn\app\manage_synchrobook_api_keys.bat` i wybierz **1. Utwórz nowy klucz**. Klucz jest powiązany z administratorem, ważny 90 dni i uprawnia wyłącznie do API synchrobooków. Skopiuj go do pola **Klucz API synchrobooków** w zakładce **Nokturn**, podaj adres serwera i połącz. **Nie podajesz narzędziu loginu ani hasła do konta.** Tajny klucz pozostaje tylko w pamięci procesu i nie jest zapisywany w projekcie. Nie podawaj klucza na czacie.
3. Wyszukaj i wybierz audiobook, następnie wybierz **Pobierz EPUB wybranego audiobooka**. Możesz również wskazać lokalną kopię tego samego EPUB. Serwer przy imporcie porówna pełną sumę SHA-256, więc inny plik lub wydanie zostanie odrzucone.
4. W zakładce **Przygotuj** wskaż lokalny folder z nagraniem tego audiobooka. Obsługiwane pliki muszą leżeć bezpośrednio w tym folderze. Kolejność odpowiada Nokturnowi: naturalne sortowanie nazw, 2 przed 10.
5. Wpisz tytuł i autora, wybierz język i model, następnie **Rozpoznaj i dopasuj**. Dla polskiego zacznij od `small`. Większe modele wymagają więcej pamięci i czasu. Wersja 0.1 używa CPU.
6. Wybierz osobny folder projektu. Rozpoznawanie zapisuje wyniki po każdym ukończonym pliku. Ponowienie z tym samym folderem projektu wykorzysta zgodne wyniki; zmiana zawartości pliku, modelu albo języka unieważnia odpowiednią pamięć. Oryginalne audio i EPUB nie są zmieniane.
7. W **Sprawdź dopasowania** sprawdź próbki dopasowań. Widoczny jest oryginalny tekst EPUB oraz rozpoznane audio w danym przedziale. `alignment-report.json` pokazuje pokrycie i niedopasowane akapity. Strona tytułowa, przypisy czy zakończenie wydawnicze mogą nie występować w nagraniu; nie dostają fikcyjnych kotwic.
8. Wybierz **Zbuduj / odśwież paczkę ZIP**. Powstanie `synchrobook.nokturn-sync.zip` zawierający tylko `manifest.json` z odciskami źródeł i znacznikami czasu. EPUB, nagranie i pomocnicza transkrypcja nie są dołączane.
9. Wybierz właściwy tytuł w Nokturnie, potwierdź sprawdzenie dopasowania i prześlij paczkę. Serwer sprawdzi pełne sumy plików audio, kolejność, rozmiary, długości, sumę EPUB i granice akapitów/zdań. Duży audiobook wymaga czasu na odczyt nagrania po stronie serwera.
10. Po sukcesie otwórz książkę ponownie w Nokturnie. Import zastępuje dane synchronizacji, **nie zmienia tekstu EPUB, plików audio ani postępu słuchania/czytania**.

Import jest wspólny dla biblioteki. Klucz musi należeć do administratora, ale nie pozwala logować się do konta ani zarządzać innymi opcjami Nokturna. W tym samym pliku `manage_synchrobook_api_keys.bat` wybierz 2, aby wyświetlić identyfikatory kluczy, lub 3, aby odwołać wybrany klucz. Serwer przechowuje wyłącznie skrót tajnego klucza; nie da się go ponownie odczytać. W razie zgubienia lub wygaśnięcia utwórz nowy. Odebranie uprawnień administratora lub unieważnienie sesji właściciela unieważnia także jego klucze. Odmowa importu nie usuwa wcześniejszej synchronizacji. Serwer zapamiętuje źródła importu i odmawia podawania tych kotwic, jeśli EPUB lub lista/statystyki plików audio później się zmienią — wtedy potrzebne jest ponowne dopasowanie.

## Dokładność i ograniczenia

- Rozpoznane słowa służą do znalezienia akapitów i zdań **w oryginalnym EPUB**. Nie tworzymy zastępczego e-booka z transkrypcji.
- Algorytm jest oparty na funkcjach dopasowania Nokturna. Używa kotwic fraz i dopasowania tekstu; nie dzieli całej książki proporcjonalnie na wymyślone czasy.
- Kolejny plik rozpoczyna się po pełnej długości poprzedniego, także po ciszy lub muzyce. Numer rozdziału EPUB nie musi odpowiadać numerowi pliku audio.
- Pewność rozpoznania i dopasowania nie daje gwarancji bezbłędności. Sprawdź próbki, szczególnie powtarzające się teksty, wydania skrócone, przypisy, muzykę i obce języki. Niskie pokrycie wymaga wyjaśnienia lub ponownego rozpoznania lepszym modelem. Niepotwierdzone akapity pozostają w raporcie bez kotwic.
- Obsługiwany jest EPUB z akapitami `<p>`, tak jak w synchronizacji Nokturna; PDF nie jest obsługiwany.
- Anulowanie rozpoznawania działa pomiędzy fragmentami. Pobranie/ładowanie modelu może najpierw wymagać zakończenia. Rozpoczętego importu nie przerywamy w połowie.
- Obsługiwane nagrania: MP3, M4B, M4A, OPUS, OGG, FLAC z wiarygodnym czasem odczytanym przez Mutagen. Limit paczki to 64 MiB.
- `project.json` i pamięć rozpoznawania zawierają tekst transkrypcji — trzymaj folder projektu prywatnie. Repozytorium i paczka programu nie zawierają Twoich projektów ani danych logowania.

## Testy i ZIP

```powershell
python -m unittest discover -s tests -v
python tools/build_zip.py
```

Zależności testów dopasowania są w `requirements.txt`. Testy podstawowe nie pobierają modelu ani nie łączą się z produkcyjnym Nokturnem. Walidację rzeczywistego rozpoznawania i integracji opisuje `docs/validation.md`.

Silnik rozpoznawania: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), lokalny CPU INT8, znaczniki słów i VAD. Brak płatnego API transkrypcji.
