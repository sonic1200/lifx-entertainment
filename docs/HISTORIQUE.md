# LIFX Entertainment : historique et notes de référence

Ce document résume comment le projet a été conçu, les décisions prises et les pièges
découverts en route. Il sert de référence pour les prochaines évolutions.

- Dépôt : https://github.com/sonic1200/lifx-entertainment (public, branche `main`)
- Auteur des commits : Nicolas Mivielle <sonic1200@gmail.com>, adresse configurée pour ce dépôt seulement
- Licence : Apache 2.0 (comme le plugin Hue dont il s'inspire)

## 1. Objectif

Avoir dans Music Assistant le même plugin que **Hue Lights Sync**
(https://www.music-assistant.io/plugins/hue-entertainment/), mais pour des ampoules **LIFX**.
Les lumières réagissent à la musique (beats, énergie, couleurs de la pochette) en
synchronisation avec l'audio.

Point de départ : https://github.com/music-assistant/hue-entertainment

## 2. Ce que contenait vraiment la référence Hue

- Le dépôt `music-assistant/hue-entertainment` ne contient **que la bibliothèque**
  (DTLS / protocole HueStream).
- Le **plugin** se trouve dans le serveur, dans `music-assistant/server`, sous
  `music_assistant/providers/hue_entertainment/`. Il est composé de `analyzer.py`,
  `bridge.py`, `provider.py`, `setup_flow.py`, `settings.py`, `constants.py`, `strings.json`
  et `manifest.json`.
- Le projet LIFX reprend donc **les deux parties** : une bibliothèque et un provider MA.

## 3. Structure du projet

| Chemin | Rôle |
| --- | --- |
| `lifx_entertainment/` | Bibliothèque asyncio sans dépendance pour le protocole LAN LIFX |
| `music_assistant_provider/lifx_entertainment/` | Provider Music Assistant « LIFX Lights Sync » |
| `tests/` | Tests unitaires et de bout en bout contre de fausses ampoules sur localhost |
| `tests/ma/` | Tests d'intégration contre le vrai serveur MA 2.10.6, ignorés s'il n'est pas installé |
| `scripts/install_ma_addon.sh` | Installation dans le conteneur de l'add-on MA (modes `install`, `watch` et `check`) |
| `.github/workflows/test.yml` | CI : ruff, mypy et pytest de Python 3.11 à 3.14 |

### Bibliothèque `lifx_entertainment/`

- `protocol.py` : encodage et décodage des paquets (en-tête de 36 octets, `struct "<HHI8s6sBBQHH"`,
  protocole 1024 avec les bits addressable et tagged), plus la conversion RGB 16 bits → HSBK.
- `transport.py` : un socket UDP partagé (port 56700). Les requêtes sont associées à leurs
  réponses par `(serial, sequence)`, avec des retries, et le streaming est en envoi sans
  accusé de réception.
- `api.py` : `LifxLanAPI` couvre le label, le groupe, le produit, l'état, la détection des
  zones (étendues, puis legacy, sinon aucune), le snapshot/restore, l'allumage et les couleurs
  par zone.
- `discovery.py` : découverte par broadcast `GetService`, renvoyé toutes les 0,6 s, plus
  sondage d'IP explicites.
- `areas.py` : construction des « zones de lumière » selon le mode de regroupement, découpe
  des bandeaux multizone en 8 segments maximum, et positions réparties sur l'axe x de -1 à 1.
- `session.py` : `EntertainmentSession` capture l'état, allume les lampes éteintes (mises
  au noir d'abord), envoie les images avec un plafond de 20 msg/s par appareil, ignore les
  doublons, renvoie un keepalive toutes les secondes, puis restaure l'état à l'arrêt.

Messages LIFX utilisés : GetService 2/3, Label 23/25, Version 32/33, Group 51/53,
LightGet 101/107, SetColor 102, SetPower 117, Ack 45, StateUnhandled 223, multizone legacy
501/502/503/506 et multizone étendu 510/511/512 (82 zones par message).

### Provider `music_assistant_provider/lifx_entertainment/`

- Il reprend la structure du provider Hue **de la version 2.10.6**, celle qui tourne sur le
  serveur, et non celle de `main`, dont l'API diffère.
- Chaque zone de lumière s'enregistre comme un client Sendspin externe en processus avec
  `register_external_player`. Elle utilise les rôles `BridgeVisualizerRole` et
  `BridgeColorRole` et devient un lecteur de type `PlayerType.LIGHT`.
- Une boucle de rendu à 20 Hz s'exécute en avance sur la lecture de la valeur de latence.
  La session démarre avec 3 tentatives espacées d'1 s, et l'arrêt attend 2 s pour survivre
  aux changements de piste.
- `analyzer.py` est copié du plugin Hue. Seul changement : le plafond de palette est passé de
  0,85 à 1,0, parce que Hue bridait pour son gamut.
- Le parcours de configuration se fait en trois étapes : saisie du broadcast et des IP
  supplémentaires, découverte, puis choix des lampes et du regroupement. Les appareils sont
  stockés en JSON dans `setup_data`.
- Une nouvelle découverte toutes les 10 min suit les changements d'IP (DHCP). La disposition
  des zones n'est mise à jour qu'au chargement, et seulement si une détection multizone
  réussit.
- Réglages modifiables à chaud, sans recharger le plugin : luminosité, mode de couleur,
  latence, transition et allumage des lampes éteintes.

### Modes de regroupement

`group` (par défaut) crée un lecteur par groupe ou pièce de l'app LIFX. `all` crée un seul
lecteur avec toutes les lampes. `light` crée un lecteur par lampe.

### Valeurs par défaut

Luminosité 100, mode `smooth`, latence 100 ms, transition 50 ms, allumage des lampes éteintes
activé, broadcast `255.255.255.255`.

## 4. Environnement de l'utilisateur

- Home Assistant OS avec l'add-on Music Assistant **2.10.6**. Slug `d5369777_music_assistant`,
  conteneur `addon_d5369777_music_assistant`, venv `/app/venv`, Python 3.14.
- Ampoules trouvées sur le LAN au moment du développement :

| Nom | IP | Produit | Groupe |
| --- | --- | --- | --- |
| Globe Droite | 192.168.0.210 | 93 | Cuisine |
| Globe Gauche | 192.168.0.96 | 1 | Cuisine |
| globe milieu | 192.168.0.54 | 181 | Cuisine |
| Lampe TV | 192.168.0.249 | | Salon |
| Lampe sous sol | 192.168.0.228 | | sous sol |

- Le bandeau **« Bandeau Canapé » (LIFX Z)** et l'**Original 1000** n'ont pas répondu, sans
  doute parce qu'ils étaient coupés au secteur. Le support multizone n'a donc été testé que
  sur de fausses ampoules.

## 5. Pièges découverts (important)

1. **Les dépendances des plugins ne s'installent pas automatiquement.** MA n'installe les
   `requirements` du manifest que sous la forme `nom==version` depuis PyPI. Avant la
   publication sur PyPI (0.1.0, le 2026-10-15), le script installait donc la bibliothèque
   avec `uv pip install` depuis l'archive GitHub. Le manifest épingle désormais
   `lifx-entertainment==0.1.0`.
2. **Le plugin disparaît quand le conteneur est recréé** : à chaque mise à jour de MA, et
   parfois au redémarrage. Il faut relancer le script, ou utiliser le mode `watch` dans les
   `init_commands` de l'add-on SSH (voir le README).
3. **Les traductions ne sont pas lues depuis `strings.json` à l'exécution.** MA compile tous
   les `strings.json` dans `music_assistant/translations/en.json` au moment du build, et à
   l'exécution il ne lit que `translations/<langue>.json`. Le script d'installation fusionne
   donc nos chaînes (`strings.json` pour l'anglais, `translations/fr.json` pour le français)
   sous le préfixe `provider.lifx_entertainment.`. Sans cette étape, l'interface afficherait
   des clés brutes.
4. **Bug UDP sous Windows** : un ICMP « port unreachable », reçu par exemple en sondant une IP
   sans ampoule, fait échouer `recvfrom` avec l'erreur 10054. La boucle proactor d'asyncio
   arrête alors définitivement la lecture du socket. Le correctif désactive
   `SIO_UDP_CONNRESET` via `WSAIoctl` (ctypes), car Python n'expose pas ce code d'ioctl.
   Linux, donc Home Assistant, n'est pas concerné.
5. **MA ne s'importe pas tel quel sous Windows**, à cause du module Unix `resource`. Les
   tests `tests/ma/` le remplacent par un module factice.
6. **`aiolibdatachannel`**, une dépendance native de MA, ne compile pas sous Windows. Pour
   les tests locaux, MA a été installé avec `--no-deps` et ses dépendances ajoutées à la main.

## 6. Vérifications effectuées

- **40 tests passent.** Ils couvrent le protocole, les zones, la découverte, le cycle de vie
  et la restauration d'une session, la limite de débit, les reprises, l'analyzer et
  l'intégration avec MA. ruff et mypy (en mode strict, sur la bibliothèque) sont propres.
- **Tests d'intégration contre le vrai MA 2.10.6** (`tests/ma/test_provider.py`) :
  - Le provider complet est chargé avec le vrai serveur Sendspin et ses rôles bridge. De
    l'audio PCM synthétique passe par le vrai extracteur de features. Les fausses ampoules
    changent de couleur avec la musique, puis l'état d'origine est restauré à l'arrêt. Le
    lecteur est bien enregistré en `PlayerType.LIGHT`.
  - Le parcours de configuration passe par le vrai `SetupSession` de MA, y compris la
    validation des formulaires et le cas « aucune lampe trouvée ».
  - Les réglages modifiés à chaud ne rechargent pas le plugin, alors qu'une modification
    mixte le recharge.
- **Scripts de validation de MA** (`check_manifests`, `check_config_entries`,
  `check_translatable_labels`, `check_provider_icons`, `build_translations`) : tous OK avec
  le plugin copié dans l'arborescence du serveur. Les 31 chaînes se résolvent en anglais et
  en français via le vrai `TranslationController`.
- **Découverte réelle depuis le PC Windows** : les 5 ampoules listées plus haut ont été
  trouvées.

**Pas encore fait :**
- Installer le plugin sur le serveur Home Assistant et le tester avec les vraies ampoules
  pendant une lecture.
- Tester un vrai bandeau multizone (le Z était hors ligne).

## 7. Installation (rappel)

1. Installer l'add-on « Advanced SSH & Web Terminal » et désactiver son « protection mode ».
2. Dans son terminal :
   ```sh
   mkdir -p /config/lifx-entertainment
   curl -fsSL -o /config/lifx-entertainment/install_ma_addon.sh \
     https://raw.githubusercontent.com/sonic1200/lifx-entertainment/main/scripts/install_ma_addon.sh
   sh /config/lifx-entertainment/install_ma_addon.sh
   ```
3. Dans MA : Paramètres → Plugins → Ajouter → **LIFX Lights Sync**.
4. Facultatif : ajouter dans les `init_commands` de l'add-on SSH
   `nohup sh /config/lifx-entertainment/install_ma_addon.sh watch > /dev/null 2>&1 &`.
   `sh install_ma_addon.sh check` indique si le plugin est installé.

Avertissement photosensibilité : les modes `flashing` et `energetic` produisent des flashs
rapides.

## 8. Développement local

- **Venv de travail** (hors dépôt) : `J:\Claude\_venvs\ma`, en Python 3.14. Il contient MA 2.10.6
  installé depuis le tag git, aiosendspin, pytest, ruff et mypy. Sur le second PC, l'équivalent
  est `F:\PERSO\_venvs\lifx` (MA 2.10.6 installé avec `--no-deps` et des dépendances réduites).
- **Commandes** :
  ```sh
  pytest tests
  ruff check . && ruff format --check .
  mypy lifx_entertainment
  ```
- **Clones de référence** (hors dépôt) : `J:\Claude\_ref` contient `hue-entertainment`,
  `ma-2106` (serveur au tag 2.10.6) et `ma-server` (`main`). Sur le second PC, `F:\PERSO\_ref`
  contient `hue-entertainment` et un clone partiel de `ma-server` (avec `AGENTS.md`).
- **Fins de ligne** : `.gitattributes` impose LF, car le ruff de MA l'exige. Avec
  `core.autocrlf=true`, la copie de travail reste en CRLF ; vérifier le contenu de l'index.
- **Publier une version** : créer une release GitHub `vX.Y.Z`. Le workflow
  `publish-to-pypi.yml` la publie sur PyPI (trusted publishing, environnement `pypi`) avec la
  version tirée du tag. Penser ensuite à mettre à jour `requirements` dans le manifest.
- **Quand MA est mis à jour** : comparer le provider Hue de la nouvelle version avec
  `bridge.py`, `setup_flow.py` et `provider.py`. Ce sont surtout l'API des rôles Sendspin
  (`ClientHelloVisualizerSupport`, `setup_visualizer`) et celle du parcours de configuration
  (`errors`, `translation_key`) qui ont bougé entre 2.10.6 et `main`.

## 9. Idées pour la suite

- Faire intégrer le plugin dans Music Assistant (PR sur `music-assistant/server`, en cours,
  voir la section 10). Ce serait la seule façon d'éviter le script et la réinstallation à
  chaque mise à jour.
- Piloter les appareils matriciels (Tile, Candle, Ceiling) par zone, alors qu'ils n'ont
  aujourd'hui qu'une seule couleur.
- Réintégrer automatiquement les lampes hors ligne au démarrage, alors qu'aujourd'hui elles
  sont ignorées jusqu'à la session suivante.

## 10. Revue des mainteneurs MA (2026-10-15)

La PR sur `music-assistant/server` (branche cible `dev`) a reçu trois demandes :

1. **Publier la bibliothèque sur PyPI** et l'épingler dans le manifest, comme
   `hue-entertainment`, puis expliquer dans la PR pourquoi aiolifx n'est pas utilisé.
   Fait : `lifx-entertainment` 0.1.0 est sur PyPI. Le README contient la section « Why not
   aiolifx? » : envois répétés 3 fois, un socket par lampe, API à callbacks, dépendances CLI.
2. **Extraire `analyzer.py`** (copie de celui de Hue) dans un composant commun utilisé aussi
   par Hue, sur le modèle de Telmore : `providers/music247e/` n'a pas de `manifest.json` et
   Telmore en hérite. À faire dans le fork de MA.
3. **Raccourcir commentaires et docstrings.** Fait (PR #1). Les `:param:` sont gardés là où
   un paramètre mérite une explication, comme le veut `AGENTS.md` de MA. `analyzer.py` n'a
   pas été touché pour rester identique à celui de Hue avant l'extraction.

Règle de `AGENTS.md` : ne jamais répondre sur le GitHub de MA sans l'accord explicite de
l'auteur.
