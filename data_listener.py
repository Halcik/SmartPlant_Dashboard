import serial
import json
from datetime import datetime, timedelta
from pathlib import Path

PORT = "COM15"   # Miejsce na port HC-05
BAUDRATE = 9600

DATA_DIR = Path("data_logs")  # katalog na logi JSON
DATA_DIR.mkdir(exist_ok=True)

# --- konfiguracja przyjmowania ramek ---
# oczekiwany odstęp między kolejnymi ramkami (w sekundach), używany przy przeliczaniu pola 't' z Arduino
EXPECTED_FRAME_INTERVAL_SECONDS = 60 * 60  # ~60 minut między pomiarami
# dopuszczalna odchyłka przy dopasowywaniu (sekundy)
FRAME_INTERVAL_SLACK_SECONDS = 60
# jeśli kolejne ramki przychodzą w krótszym odstępie (sekund), traktujemy je jako jedną "paczkę"/klaster
CLUSTER_MAX_INTERARRIVAL_SECONDS = 30

# bufor paczki ramek czekających na rozdzielenie timestampów
_pending_frames = []  # lista tupli oczekujących na dodanie do logów (parsed_dict, arrival_datetime) 


def parse_line(raw: str):
    """
    Parsuje linię w formacie:
      @ENV;ok=1;temp=23.4;hum=45.2;light=512
      @PLANT;name=Roślinka 1;soilRaw=523;soil=18;threshold=20;needWater=1;waterState=1;watered=1
    Zwraca dict albo None (jeśli to nie ramka zaczynająca się od '@').
    """
    raw = raw.strip()
    if not raw.startswith("@"):
        return None

    body = raw[1:] # ominięcie @
    parts = body.split(";")
    if not parts:
        return None

    kind = parts[0]  # "ENV" albo "PLANT"
    data = {"kind": kind}

    for p in parts[1:]: #pomijamy rodzaj ramki, bo już jest
        if "=" in p:
            k, v = p.split("=", 1)
            data[k] = v

    return data


def save_record(record: dict):
    """
    Zapisuje rekord do pliku JSON z datą w nazwie.
    """
    # zapis z opcjonalnym nadpisaniem timestampu
    record = dict(record)  # kopiujemy, żeby nie modyfikować oryginału
    # jeśli ts jest podane w rekordzie, zostawiamy; domyślnie current time
    ts = record.get("_forced_ts")
    if ts is None:
        ts_dt = datetime.now()
    else:
        # akceptujemy datetime lub ISO string
        if isinstance(ts, datetime):
            ts_dt = ts
        else:
            try:
                ts_dt = datetime.fromisoformat(str(ts))
            except Exception:
                ts_dt = datetime.now()

    record["timestamp"] = ts_dt.isoformat(timespec="seconds")

    today_str = ts_dt.date().isoformat()

    if record.get("kind") == "ENV":
        filename = DATA_DIR / f"env_{today_str}.jsonl"
    elif record.get("kind") == "PLANT":
        filename = DATA_DIR / f"plants_{today_str}.jsonl"
    else:
        filename = DATA_DIR / f"other_{today_str}.jsonl"

    # usuń pole pomocnicze przed zapisem
    if "_forced_ts" in record:
        record.pop("_forced_ts")

    with filename.open("a", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
        f.write("\n")


def handle_env(data: dict):
    """
    Ładne wypisanie ramki @ENV + zapis do JSON.
    """
    ok = data.get("ok", "0") == "1"
    try:
        light = int(data.get("light", "0"))
    except ValueError:
        light = 0

    if ok:
        try:
            temp = float(data.get("temp", "nan"))
            hum = float(data.get("hum", "nan"))
            print(f"[ENV] OK  | temp={temp:.1f}°C, hum={hum:.1f}%, light={light}")
        except ValueError:
            print(f"[ENV] DANE NIEPRAWIDŁOWE, light={light}, raw={data}")
    else:
        print(f"[ENV] BŁĄD DHT | light={light}")

    # nie zapisujemy tutaj bezpośrednio - zapis wykonuje główny loop (allow clustering)
    return data


def handle_plant(data: dict):
    """
    Ładne wypisanie ramki @PLANT + zapis do JSON.
    """
    name = data.get("name", "?")

    try:
        soil = int(data.get("soil", "0"))
        soil_raw = int(data.get("soilRaw", "0"))
        threshold = int(data.get("threshold", "0"))
        need_water = data.get("needWater", "0") == "1"
        watered = data.get("watered", "0") == "1"
        water_state = int(data.get("waterState", "-1"))  # -1,0,1
    except ValueError:
        print(f"[PLANT {name}] BŁĄD PARSOWANIA DANYCH: {data}")
        save_record(data)  # i tak zapisujemy surowe
        return
    
    reason = f"soil={soil}% < threshold={threshold}%, waterState={water_state}"
    if not need_water:
        status = "GLEBA OK"
    else:
        if water_state == 0:
            status = "SUCHA, NIE PODLANA (BRAK WODY W ZBIORNIKU)"
        elif water_state == 1:
            if watered:
                status = "SUCHA, PODLANA"
            else:
                status = "SUCHA, NIE PODLANA (NIEZNANY POWÓD)"
        else:
            if watered:
                status = "PODLANA (waterState nieustalony)"
            else:
                status = "SUCHA?, NIE PODLANA (waterState nieustalony)"

    print(f"[PLANT {name}] {status} | {reason}, soilRaw={soil_raw}")

    # nie zapisujemy tutaj bezpośrednio - zapis wykonuje główny loop (allow clustering)
    return data


def main():
    ser = serial.Serial(PORT, BAUDRATE, timeout=1)
    print(f"Połączono z {PORT}. Czekam na ramki @ENV / @PLANT... \n(Ctrl+C aby wyjść)\n")
    print(f"Logi JSON będą zapisywane w: {DATA_DIR.resolve()}\n")

    def _process_pending():
        """Przetwarza i zapisuje zbuforowane ramki (_pending_frames), przypisując im timestamp.
        Jeśli w rekordach jest Arduino 't' (czas w ms), to starszym ramkom cofa timestamp względem najnowszej.
        Najnowsza ramka zachowuje czas przyjścia (arrival time).
        """
        global _pending_frames
        if not _pending_frames:
            return

        # Czas przyjścia (arrival) najnowszej ramki — bierzemy z ostatniego elementu bufora
        newest_arrival = _pending_frames[-1][1]

        # Wyciągamy wartości 't' (ms z Arduino) dla każdej ramki, jeśli są.
        # Jeśli nie ma 't' albo nie da się zamienić na int, zapisujemy None.
        t_values = []
        for rec, arr in _pending_frames:
            t_raw = rec.get('t')
            try:
                t_ms = int(t_raw) if t_raw is not None else None
            except Exception:
                t_ms = None
            t_values.append(t_ms)

        # Sprawdzamy, czy w ogóle są jakieś poprawne 't'
        t_present = [t for t in t_values if t is not None]
        max_t = max(t_present) if t_present else None

        # Lista timestampów, które wymusimy przy zapisie (przez pole _forced_ts)
        forced_ts = []
        if max_t is not None:
            # Liczymy różnicę (max_t - t_i). To mówi, o ile ms dana ramka jest "starsza" względem najnowszej (tej z największym t).
            for (rec, arr), t_ms in zip(_pending_frames, t_values):
                if t_ms is None:
                    # fallback:  Brak 't' w tej ramce — na razie ustawiamy None (uzupełnimy później)
                    forced_ts.append(None)
                else:
                    delta_ms = max_t - t_ms
                    #  Cofamy czas od newest_arrival o delta_ms
                    ts = newest_arrival - timedelta(milliseconds=delta_ms)
                      # Zabezpieczenie: timestamp nie powinien wyjść "w przyszłość" względem newest_arrival
                    if ts > newest_arrival:
                        ts = newest_arrival
                    forced_ts.append(ts)
        else:
            #  Nie ma żadnych 't', rozkładamy czas sztucznie
            n = len(_pending_frames)
            for i, (rec, arr) in enumerate(_pending_frames):
                # newest gets newest_arrival; earlier ones get +1s, +2s ... gaps
                offset = n - 1 - i
                forced_ts.append(newest_arrival - timedelta(seconds=offset))

        # uzupełniamy None (ramki bez 't') na podstawie sąsiadów.
        # Strategia:
        # - jeśli mamy poprzedni timestamp, to ustawiamy -1s
        # - w przeciwnym razie szukamy następnego nie-None i cofamy o (j-i) sekund
        # - jak nic nie znajdziemy, bierzemy arrival time
        for i in range(len(forced_ts)):
            if forced_ts[i] is None:
                if i > 0 and forced_ts[i-1] is not None:
                    forced_ts[i] = forced_ts[i-1] - timedelta(seconds=1)
                else:
                    j = i+1
                    while j < len(forced_ts) and forced_ts[j] is None:
                        j += 1
                    if j < len(forced_ts) and forced_ts[j] is not None:
                        forced_ts[i] = forced_ts[j] - timedelta(seconds=(j - i))
                    else:
                        forced_ts[i] = _pending_frames[i][1]

        # Zapewnienie porządku czasowego - nie ma późniejszycc od najnowszego + rosnące
        for i in range(len(forced_ts)):
            if forced_ts[i] > newest_arrival:
                forced_ts[i] = newest_arrival
            if i > 0 and forced_ts[i] <= forced_ts[i-1]:
                forced_ts[i] = forced_ts[i-1] + timedelta(seconds=1)

        #  Zapisujemy rekordy w oryginalnej kolejności (najstarsze pierwsze)
        for (rec, arr), ts in zip(_pending_frames, forced_ts):
            rec['_forced_ts'] = ts
            save_record(rec)

        _pending_frames = []


    last_arrival = None
    try:
        while True:
            raw = ser.readline().decode(errors="ignore").strip()
            if not raw:
                continue

            parsed = parse_line(raw)
            if parsed is None:
                # zwykły log tekstowy z Arduino - ignorowany
                continue

            arrival = datetime.now()
            kind = parsed.get("kind")

            if kind == "ENV":
                handle_env(parsed)
            elif kind == "PLANT":
                handle_plant(parsed)
            else:
                print("[UNKNOWN FRAME]", parsed)
                # osobny plik na nieznane
                parsed['_forced_ts'] = arrival
                save_record(parsed) #???
                continue

            # Buforowanie ramek w klastrach
            if last_arrival is None:
                # pierwsza odebrana ramka — zaczynamy nowy klaster
                _pending_frames.append((parsed, arrival))
            else:
                delta = (arrival - last_arrival).total_seconds()
                if delta <= CLUSTER_MAX_INTERARRIVAL_SECONDS:
                    #  Ramka przyszła szybko po poprzedniej -> uznajemy, że należy do tego samego klastra
                    _pending_frames.append((parsed, arrival))
                else:
                    # Była większa przerwa -> kończymy poprzedni klaster i zapisujemy to, co było
                    _process_pending()
                    _pending_frames.append((parsed, arrival)) # już w nowym jest, jak ta większa przerwa

            last_arrival = arrival

    except KeyboardInterrupt:
        # Jeśli użytkownik przerwie program (Ctrl+C), zapisuje to, co jest w buforze
        _process_pending()
        print("\nZakończono przez użytkownika.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
