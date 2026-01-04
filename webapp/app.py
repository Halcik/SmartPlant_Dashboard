from flask import Flask, jsonify, send_from_directory
import json
from pathlib import Path

app = Flask(__name__, static_folder='static', static_url_path='/static')
DATA_DIR = Path(__file__).resolve().parent.parent / 'data_logs'


def find_latest(pattern):
    """
    Znajduje najnowszy plik pasujący do wzorca glob (np. 'env_*.jsonl')
    i zwraca ścieżkę do niego.
    Nowszość jest liczona po czasie modyfikacji pliku (mtime).
    """
    files = list(DATA_DIR.glob(pattern))
    if not files:
        return None
     # Sortujemy malejąco po czasie modyfikacji (najnowszy pierwszy)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def read_last_jsonl(path):
    """
    Czyta plik jsonl (JSON Lines) i zwraca ostatni niepusty rekord jako dict.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f if l.strip()]
            if not lines:
                return None
            return json.loads(lines[-1])
    except Exception as e:
        return None


def read_all_jsonl(path):
    """
    Czyta wszystkie poprawne linie JSON z pliku jsonl i zwraca listę dictów.
    Błędne linie są pomijane.
    """
    out = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for l in f:
                l = l.strip()
                if not l:
                    continue
                try:
                    out.append(json.loads(l))
                except Exception:
                    continue
    except Exception:
        return []
    return out


@app.route('/')
def index():
    """
    Strona główna: plik static/index.html.
    """
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/api/env')
def api_env():
    """
    Endpoint zwracający „stan środowiska” (temperatura, wilgotność, światło, poziom wody + timestamp).
    1) Bierze najnowszy plik env_*.jsonl i z niego ostatni rekord.
    2) Mapuje klucze na bardziej friendly nazwy.
    3) Poziom wody wyciąga z logsów plants_*: szuka ostatniego waterState != -1.
    """

    # Szukamy najnowszego pliku env_*.jsonl i najświeższy pomiar
    latest = find_latest('env_*.jsonl')
    if not latest:
        return jsonify({'error': 'no env logs found'}), 404
    data = read_last_jsonl(latest)
    if data is None:
        return jsonify({'error': 'could not read env log'}), 500

    # mapowanie friendly nazw
    mapped = {
        'temperature': None,
        'humidity': None,
        'light': None,
        'water_level': None,
        'timestamp': data.get('timestamp')
    }
    # stałe klucze w logach rzutowane na float: 'temp', 'hum', 'light'
    if 'temp' in data:
        try:
            if data.get('temp') != "NaN":
                mapped['temperature'] = float(data.get('temp'))
        except Exception:
            mapped['temperature'] = data.get('temp')
    if 'hum' in data:
        try:
            if data.get('hum') != "NaN":
                mapped['humidity'] = float(data.get('hum'))
        except Exception:
            mapped['humidity'] = data.get('hum')
    if 'light' in data:
        try:
            mapped['light'] = int(data.get('light'))
        except Exception:
            mapped['light'] = data.get('light')

    # Poziom wody: wyciągamy go z logsów plants_*.jsonl - ostatni wpis, który ma waterState różny od -1
    files = list(DATA_DIR.glob('plants_*.jsonl'))
    if files:
        lines = []
        for f in files:
            lines.extend(read_all_jsonl(f))

        for entry in reversed(lines):
            ws = entry.get('waterState')
            if ws is not None:
                try:
                    ws_val = int(ws)
                    if ws_val != -1:
                        mapped['water_level'] = ws_val
                        break
                except Exception:
                    pass

    return jsonify(mapped)


@app.route('/api/plants')
def api_plants():
    """
    Endpoint zwracający listę roślin (snapshot + historia wilgotności).
    1) Czyta wszystkie plants_*.jsonl.
    2) Sortuje wpisy po timestamp (jeśli jest).
    3) Grupuje wpisy po nazwie rośliny, buduje historię wilgotności i metadane.
    4) Zwraca listę obiektów dla frontendu
    """
    files = list(DATA_DIR.glob('plants_*.jsonl'))
    if not files:
        return jsonify({'error': 'no plants logs found'}), 404

    # Czytamy wszystkie rekordy ze wszystkich plików plants_*.jsonl
    lines = []
    for f in files:
        lines.extend(read_all_jsonl(f))
    if not lines:
        return jsonify({'error': 'could not read plants log'}), 500

    # Sortujemy chronologicznie
    def ts_key(e):
        return e.get('timestamp') or ''
    try:
        lines.sort(key=ts_key)
    except Exception:
        pass

    # Grupowanie po nazwie rośliny
    grouped = {}
    for entry in lines:
        name = entry.get('name') or entry.get('id') or entry.get('plant')
        if not name:
            continue

        rec = grouped.setdefault(name, {'history': [], 'last': None, 'last_watered_ts': None, 'last_seen': None})

        # Próba wyciągnięcia wilgotności gleby jako int
        soil_val = None
        if 'soil' in entry:
            try:
                soil_val = int(entry.get('soil'))
            except Exception:
                try:
                    soil_val = int(float(entry.get('soil')))
                except Exception:
                    soil_val = None

        elif 'soilRaw' in entry:
            try:
                # jak jest już zmapowana wilgotność, bierzemy, jak nie to surowe
                soil_val = int(entry.get('soil')) if 'soil' in entry and entry.get('soil') is not None else None
            except Exception:
                soil_val = None

        # dopisujemy punkt do historii
        if soil_val is not None:
            rec['history'].append({'v': soil_val, 't': entry.get('timestamp')})

        # timestamp ostatniego pomiaru
        rec['last_seen'] = entry.get('timestamp')

        #  lastWatered: wykrywamy podlanie po polu 'watered' = 1
        w = entry.get('watered')
        try:
            if w is not None and str(w).strip() != '' and int(float(w)) > 0:
                rec['last_watered_ts'] = entry.get('timestamp')
        except Exception:
            pass

        rec['last'] = entry

    # sortujemy nazwy roślin, jak kończy się numerem, to po numerze:
    def sort_key(n):
        import re
        m = re.search(r"(\d+)$", n)
        return int(m.group(1)) if m else n

    plant_names = sorted(grouped.keys(), key=sort_key)

    result = []
    idx = 1
    for name in plant_names:
        rec = grouped[name]
        last = rec.get('last') or {}
        # Ograniczamy historię do ostatnich 15 wpisów
        history_full = rec.get('history', [])[-15:]

        plant_obj = {
            'id': idx,
            'name': name,
            'moisture': int(last.get('soil')) if last.get('soil') is not None else None,
            'threshold': int(last.get('threshold')) if last.get('threshold') is not None else None,
            # lastWatered ustawiamy tylko, jeśli logi wykazały faktyczne podlanie
            'lastWatered': rec.get('last_watered_ts'),
            'lastSeen': rec.get('last_seen'),
            'history': history_full
        }
        result.append(plant_obj)
        idx += 1

    # frontend zawsze dostanie co najmniej 4 „sloty” (placeholder, jeśli nie ma)
    while len(result) < 4:
        result.append({'id': len(result) + 1, 'name': f'Roślina {len(result)+1}', 'moisture': None, 'threshold': None, 'lastWatered': None, 'history': []})

    return jsonify(result)


if __name__ == '__main__':
    # dev server
    app.run(host='0.0.0.0', port=5000, debug=True)
