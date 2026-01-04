const defaultConfig = {
  plant1_name: "Monstera Deliciosa",
  plant2_name: "Fikus Benjamina",
  plant3_name: "Sansewieria",
  plant4_name: "Pothos Złocisty"
};

// dobiera klasę CSS dla paska wilgotności w zależności od progu podlewania
function getMoistureClass(moisture, threshold) {
  if (moisture < threshold) return 'low';
  if (moisture < threshold + 15) return 'medium';
  return '';
}

// Renderowanie kart roślin na stronie na podstawie danych z backendu
function renderPlants(plantsData) {
  const plantsGrid = document.getElementById('plants-grid');
  plantsGrid.innerHTML = '';

  if (!Array.isArray(plantsData)) return;

  // dla każdej rośliny tworzymy kartę i wstawiamy do DOM
  plantsData.forEach((plant) => {
    const plantName = plant.name || defaultConfig[`plant${plant.id}_name`] || (`Roślina ${plant.id}`);
    const moistureClass = getMoistureClass(plant.moisture, plant.threshold || 50);

    const plantCard = document.createElement('div');
    plantCard.className = 'plant-card';

    const history = Array.isArray(plant.history) ? plant.history : [];

    // Formatowanie timestampu do tooltipa na wykresie (krótsza forma)
    function formatTimestampChart(ts) {
      if (!ts) return '';
      const d = new Date(ts);
      if (isNaN(d.getTime())) {
        try {
          const parts = ts.replace(' ', 'T');
          const d2 = new Date(parts);
          if (!isNaN(d2.getTime())) return formatDateChart(d2);
        } catch (e) { }
        return '';
      }
      return formatDateChart(d);
    }

    // helper: dodaje zero z przodu dla wartości <10
    function padChart(n) { return n < 10 ? '0' + n : n; }

    // Format daty: DD.MM.RRRR HH:MM (dla tooltipa wykresu)
    function formatDateChart(d) {
      const day = padChart(d.getDate());
      const month = padChart(d.getMonth() + 1);
      const year = d.getFullYear();
      const hours = padChart(d.getHours());
      const mins = padChart(d.getMinutes());
      return `${day}.${month}.${year} ${hours}:${mins}`;
    }


    // Budujemy HTML „słupków” wykresu z historii:
    // - item może być liczbą albo obiektem {v: wartość, t: timestamp}
    // - wysokość słupka to value%
    // - tooltip pokazuje wartość i (opcjonalnie) czas
    const chartBars = history.map((item) => {
      const value = (typeof item === 'object' && item.v !== undefined) ? item.v : item;
      const timestamp = (typeof item === 'object' && item.t !== undefined) ? item.t : null;
      const formattedTs = formatTimestampChart(timestamp);
      const tooltipText = formattedTs ? `<strong>${value}%</strong>${formattedTs}` : `<strong>${value}%</strong>`;
      return `
        <div class="chart-bar" style="height: ${value}%" title="${formattedTs}">
          <div class="chart-tooltip">${tooltipText}</div>
        </div>
      `;
    }).join('');

    // Budujemy etykiety osi X (godziny:minuty) - co druga etykieta dla lepszej czytelności
    const xLabels = history.map((item, index) => {
      if (index % 2 !== 0) return '<div class="x-label"></div>'; // pusty dla co drugiego wpisu
      const timestamp = (typeof item === 'object' && item.t !== undefined) ? item.t : null;
      if (!timestamp) return '<div class="x-label"></div>';
      const d = new Date(timestamp);
      if (isNaN(d.getTime())) return '<div class="x-label"></div>';
      const hours = padChart(d.getHours());
      const mins = padChart(d.getMinutes());
      return `<div class="x-label">${hours}:${mins}</div>`;
    }).join('');

    // Formatowanie timestampu do pól „Ostatnie podlewanie” / „Ostatni pomiar” (pełniejsza forma)
    function formatTimestampFull(ts) {
      if (!ts) return '-';
      const d = new Date(ts);
      if (isNaN(d.getTime())) {
        try {
          const parts = ts.replace(' ', 'T');
          const d2 = new Date(parts);
          if (!isNaN(d2.getTime())) return formatDateFull(d2);
        } catch (e) { }
        return ts;
      }
      return formatDateFull(d);
    }

    function padFull(n) { return n < 10 ? '0' + n : n; }

    // Format daty: DD.MM.RRRR HH:MM (dla wyświetlania w karcie)
    function formatDateFull(d) {
      const day = padFull(d.getDate());
      const month = padFull(d.getMonth() + 1);
      const year = d.getFullYear();
      const hours = padFull(d.getHours());
      const mins = padFull(d.getMinutes());
      return `${day}.${month}.${year} ${hours}:${mins}`;
    }

    // Składamy HTML karty rośliny
    plantCard.innerHTML = `
      <div class="plant-header">
        <div class="plant-icon">🪴</div>
        <h3 class="plant-name">${plantName}</h3>
      </div>

      <div class="plant-info">
        <div class="info-item">
          <div class="info-label">Wilgotność</div>
          <div class="info-value">${plant.moisture ?? '-'}%</div>
          <div class="moisture-bar">
            <div class="moisture-fill ${moistureClass}" style="width: ${plant.moisture ?? 0}%"></div>
          </div>
        </div>

        <div class="info-item">
          <div class="info-label">Próg Podlewania</div>
          <div class="info-value">${plant.threshold ?? '-'}%</div>
        </div>
      </div>

      <div class="info-item">
        <div class="info-label">Ostatnie Podlewanie</div>
        <div class="info-value" style="font-size: 16px;">${plant.lastWatered ? formatTimestampFull(plant.lastWatered) : '-'}</div>
      </div>
      <div class="info-item">
        <div class="info-label">Ostatni pomiar</div>
        <div class="info-value" style="font-size: 16px;">${plant.lastSeen ? formatTimestampFull(plant.lastSeen) : '-'}</div>
      </div>

      <div class="chart-container">
        <div class="chart-title">Historia wilgotności (ostatnie ${history.length} pomiarów)</div>
        <div class="chart-wrapper">
          <div class="y-axis">
            <div class="y-label">100%</div>
            <div class="y-label">50%</div>
            <div class="y-label">0%</div>
          </div>
          <div class="chart">
            ${chartBars}
          </div>
        </div>
        <div class="x-axis">
          ${xLabels}
        </div>
      </div>
    `;

    plantsGrid.appendChild(plantCard);
  });
}

// Pobranie danych środowiskowych z backendu (/api/env
async function fetchEnv() {
  try {
    const res = await fetch('/api/env');
    if (!res.ok) throw new Error('no env');
    return await res.json();
  } catch (e) {
    return null;
  }
}

// Pobranie danych roślin z backendu (/api/plants)
async function fetchPlants() {
  try {
    const res = await fetch('/api/plants');
    if (!res.ok) throw new Error('no plants');
    return await res.json();
  } catch (e) {
    return null;
  }
}

// Mapowanie światła
function describeLight(value) {
  // brak danych
  if (value === undefined || value === null) return { label: '-', level: null };

  // spróbuj zamienić na liczbę
  const v = Number(value);
  if (!Number.isFinite(v)) return { label: '-', level: null };

  // progi dopasowane do obserwacji, mogą wymagać zmiany
  if (v <= 20) return { label: 'Ciemno', level: v };
  if (v <= 250) return { label: 'Półmrok', level: v };
  if (v <= 700) return { label: 'Sztuczne światło', level: v };
  return { label: 'Światło dzienne', level: v };
}


// Aktualizacja UI dla sekcji środowiska
function updateEnvUI(env) {
  if (!env) return;
  // Elementy DOM, które będą aktualizowane
  const tEl = document.getElementById('temperature');
  const hEl = document.getElementById('humidity');
  const lEl = document.getElementById('light');
  const wEl = document.getElementById('water-status');

  if (env.temperature !== undefined && env.temperature !== null) {
    const t = (typeof env.temperature === 'number') ? env.temperature.toFixed(1) : env.temperature;
    tEl.textContent = t;
  } else {
    tEl.textContent = '-';
  }

  if (env.humidity !== undefined && env.humidity !== null) {
    hEl.textContent = (typeof env.humidity === 'number') ? Math.round(env.humidity) : env.humidity;
  } else {
    hEl.textContent = '-';
  }

  const light = describeLight(env.light);
  lEl.textContent = (light.level === null) ? '-' : `${light.label}`;

  // Status wody: 0 = brak, 1 = jest
  if (env.water_level !== undefined && env.water_level !== null) {
    wEl.textContent = env.water_level === 0 ? 'Brak wody' : (env.water_level === 1 ? 'Woda dostępna' : env.water_level);
    if (env.water_level === 0) {
      wEl.classList.remove('water-ok');
      wEl.classList.add('water-low');
    } else {
      wEl.classList.remove('water-low');
      wEl.classList.add('water-ok');
    }
  } else {
    wEl.textContent = '-';
    wEl.classList.remove('water-low');
    wEl.classList.add('water-ok');
  }
}

// Odświeżenie danych (env + plants) i aktualizacja UI
async function refresh() {
  const [env, plants] = await Promise.all([fetchEnv(), fetchPlants()]);

  if (env) updateEnvUI(env);

  if (plants) {
    if (Array.isArray(plants)) {
      renderPlants(plants);
    } else if (plants.plants && Array.isArray(plants.plants)) {
      renderPlants(plants.plants);
    } else {
      const arr = Object.keys(plants).map(k => plants[k]);
      renderPlants(arr);
    }
  }
}

// Pierwsze załadowanie danych po starcie strony
refresh();
// Odświeżanie co 5s
setInterval(refresh, 5000);
