# DowFlow V13

DowFlow est une application Windows Flask pour telecharger, organiser et lire des videos et de la musique localement.

## Fonctionnalites

- Telechargement video et audio avec `yt-dlp`.
- Acceleration optionnelle avec `aria2c` et connexions paralleles.
- Qualite adaptative, sous-titres VTT et reprise des telechargements.
- Recherche musicale, pochettes, favoris et bibliotheque locale.
- Extraction navigateur avec Playwright pour les sites non pris en charge directement.
- Historique SQLite, jobs asynchrones et organisation par domaine.

## Prerequis

- Windows 10 ou version ulterieure.
- Python 3.10 ou ulterieur dans le `PATH`.
- Git pour les mises a jour automatiques du projet.
- Connexion Internet.

`start.bat` detecte ou installe Playwright Chromium, `aria2c` et FFmpeg via WinGet quand ils sont absents. Node.js LTS peut fournir davantage de formats YouTube.

## Lancement

Depuis la racine du projet :

```powershell
.\start.bat
```

Au demarrage, le script :

1. Verifie le dernier commit de `main` sur [GitHub](https://github.com/diego1505-Art/DowFlow-V13).
2. Sauvegarde temporairement les changements suivis avec Git si necessaire.
3. Applique une mise a jour fast-forward puis restaure les changements locaux.
4. Cree `.venv` si besoin.
5. Verifie `requirements.txt` et met a jour `yt-dlp`.
6. Verifie Playwright, `aria2c` et FFmpeg.

L'application est ensuite disponible sur <http://127.0.0.1:5001>.

Pour une installation manuelle :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
python app.py
```

## Diagnostic

Le centre de diagnostic utilise le venv, les couleurs ANSI et des controles non destructifs :

```powershell
.\debug.bat
```

Il peut verifier Python, les dependances, les imports, FFmpeg, FFprobe, `aria2c`, Chrome, Playwright, le reseau, SQLite, les APIs Flask et le commit disponible sur GitHub. Les resultats sont conserves dans `logs/debug_*.log`.

## Tests

```powershell
python -m unittest discover -v
```

## Cookies et donnees locales

Certains sites demandent une session. Un profil Chrome local ou `youtube_cookies.txt` au format Netscape peut etre utilise. Ces fichiers donnent acces a vos comptes et restent exclus du depot par `.gitignore`.

Les telechargements, logs, bases SQLite, profils navigateur, caches Python et environnements virtuels sont locaux et ignores par Git.

## Structure

| Fichier ou dossier | Role |
| --- | --- |
| `app.py` | Serveur Flask et routes HTTP |
| `playlist.py` | Telechargements video et audio |
| `music.py` | Recherche et bibliotheque musicale |
| `music_dataset.py` | Interface du catalogue local |
| `browser_extractor.py` | Extraction via navigateur |
| `url_expanders/` | Expansion des URLs et episodes |
| `debug_center.py` | Diagnostic interactif |
| `templates/` et `static/` | Interface web |
| `downloads/` | Medias telecharges localement |
| `logs/` | Journaux locaux |

## Configuration

Les options principales sont dans `config.py` :

- `DOWFLOW_BROWSER_VISIBLE` affiche le navigateur Playwright.
- `DOWFLOW_CONNECTIONS` force le nombre de connexions paralleles.
- `DOWFLOW_PROXY_AUTO` active la recuperation de proxys publics.
- `DOWFLOW_YOUTUBE_COOKIES` definit un fichier de cookies alternatif.

