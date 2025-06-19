# 🌍 Seismisk Analyse Platform

En avanceret seismologisk analyseplatform til realtids jordskælvsanalyse med professionelle værktøjer til seismisk dataprocessering.

## 🚀 Live Demo

**[Kør applikationen her](https://your-app-name.streamlit.app)** ← *URL kommer efter deployment*

## ✨ Hovedfunktioner

### 📡 Data Integration
- **IRIS FDSN integration** - Automatisk hentning af seismiske data
- **Global station netværk** - Adgang til 1000+ seismiske stationer
- **Real-time katalog** - Seneste jordskælv fra magnitude 5.0+

### 🔬 Avanceret Analyse
- **Ms Magnitude beregning** - Efter IASPEI 2013 standarder
- **7 filter typer** - P-bølger, S-bølger, overfladebølger, teleseismisk
- **P-bølge STA/LTA detektion** - Automatisk arrival time picking
- **FFT spektral analyse** - Frekvensindhold af overfladebølger
- **SNR beregning** - Signal-to-Noise ratio over tid

### 📊 Visualiseringer
- **Interaktivt verdenskort** - Jordskælv og station locations
- **Multi-panel plots** - Simultane visninger af N/E/Z komponenter
- **Før/efter sammenligning** - Effekt af signal processing
- **Real-time plotting** - Plotly-baserede interactive grafer

### 📈 Professional Output
- **Excel eksport** - Komplet data + metadata til videre analyse
- **Timing validering** - Fysisk realistiske P-bølge hastigheder
- **Data kvalitetsvurdering** - SNR og støj statistikker

## 🛠️ Teknisk Stack

- **Frontend:** Streamlit + Plotly + Folium
- **Seismologi:** ObsPy framework
- **Data:** IRIS Data Management Center
- **Processing:** NumPy + SciPy signal processing
- **Export:** XlsxWriter for Excel integration

## 📋 Krav

### Python Dependencies
```
streamlit>=1.28.0
obspy>=1.4.0
pandas>=1.5.0
numpy>=1.21.0
plotly>=5.15.0
folium>=0.14.0
streamlit-folium>=0.13.0
scipy>=1.9.0
xlsxwriter>=3.1.0
```

### System Dependencies
```
build-essential
libproj-dev
proj-data
proj-bin
libgeos-dev
```

## 🚀 Installation

### Lokal Installation
```bash
# Clone repository
git clone https://github.com/dit-brugernavn/seismic-analysis.git
cd seismic-analysis

# Installer dependencies
pip install -r requirements.txt

# Kør applikationen
streamlit run Seis3_1.py
```

### Docker Installation
```bash
# Build image
docker build -t seismic-analysis .

# Kør container
docker run -p 8501:8501 seismic-analysis
```

## 📖 Brugsanvisning

### 1. Vælg Jordskælv
- Browse seneste jordskælv på interaktivt kort
- Filtrer efter magnitude (5.0-8.5)
- Klik på jordskælv for at se tilgængelige stationer

### 2. Vælg Analyse Station
- 4 optimal placerede stationer (800-2200 km afstand)
- IRIS verificerede stationer prioriteres
- Automatisk beregning af P/S/Surface ankomsttider

### 3. Signal Processing
- **Ingen filtrering:** Se original displacement data
- **Bredband:** Standard analyse filter (0.01-25 Hz)
- **Overfladebølger:** Optimal til Ms magnitude (0.02-0.5 Hz)
- **P-bølger:** Isolerer primære bølger (1.0-10 Hz)
- **S-bølger:** Isolerer sekundære bølger (0.5-5.0 Hz)

### 4. Avanceret Analyse
- **P-bølge zoom:** STA/LTA automatisk detektion
- **FFT spektrum:** Frekvens analyse af overfladebølger
- **SNR monitoring:** Signal kvalitet over tid
- **Timing validering:** Fysisk realistiske hastigheder

### 5. Excel Eksport
- Komplet metadata (jordskælv + station info)
- Downsampled tidsserier (2 Hz for Excel effektivitet)
- Both rådata og processeret displacement
- Ms magnitude beregning og forklaring

## 🔬 Videnskabelig Baggrund

### Ms Magnitude Formel
```
Ms = log₁₀(A/T) + 1.66×log₁₀(Δ) + 3.3
```
- **A:** Maksimum overfladebølge amplitude (μm)
- **T:** Periode (20s reference)
- **Δ:** Epicentral afstand (grader)

### Filter Specifikationer
| Filter Type | Frekvens Range | Anvendelse |
|-------------|----------------|------------|
| Bredband | 0.01-25 Hz | Generel analyse |
| P-bølger | 1.0-10 Hz | Primære kompressionsbølger |
| S-bølger | 0.5-5.0 Hz | Sekundære forskydningsbølger |
| Overfladebølger | 0.02-0.5 Hz | Ms magnitude beregning |
| Teleseismisk | 0.02-2.0 Hz | Fjerne jordskælv |
| Lang-periode | 0.005-0.1 Hz | Tektoniske signaler |

## 📚 Referencer

- **IASPEI 2013:** International standards for magnitude determination
- **ObsPy:** Beyreuther et al. (2010) - Seismological framework
- **IRIS DMC:** Data Management Center for global seismology
- **TauP:** Crotwell et al. (1999) - Seismic travel time calculations

## 🤝 Bidrag

Bidrag er velkomne! Send pull requests eller åbn issues for:
- Bug fixes
- Nye analyse metoder
- Performance forbedringer
- Dokumentation updates

## 📄 Licens

Dette projekt er open source under MIT License.

## 👨‍💻 Udvikler

Udviklet af Philip K. Jakobsen som avanceret seismologisk analyseværktøj.

**Kontakt:** pj@sg.dk

---

### 🔗 Links
- **Live App:** https://gvseis.streamlit.app
- **GitHub:** https://github.com/geovidenskab/gvseis
- **IRIS DMC:** https://ds.iris.edu/ds/nodes/dmc/
- **ObsPy Documentation:** https://docs.obspy.org/

### ⭐ Support

Hvis dette projekt har hjulpet dig, giv det en stjerne på GitHub!
