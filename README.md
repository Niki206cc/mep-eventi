# MEP Eventi

Importa in automatico gli eventi delle valli su **Montagne & Paesi** (WordPress + The Events Calendar).

Per ogni evento trovato:
1. legge la scheda dalla fonte (API o pagina web);
2. scarica la **locandina** (immagine o prima pagina del PDF) e sceglie la migliore;
3. fa leggere tutto all'**IA**, compresa la locandina, che estrae date, orari, luogo e costo e scrive una **descrizione originale**;
4. scarta ciò che non è un evento, gli eventi passati, i **duplicati** (stesso evento su più fonti o già presente sul sito) e, se vuoi, gli appuntamenti fissi (corsi settimanali, mercati);
5. crea l'evento nel calendario con immagine in evidenza, luogo, categoria e tag (comune e zona), **in bozza**;
6. ti manda il riepilogo su **Telegram** con i link per approvare.

Se alla fonte cambia qualcosa (data, orario, testo), l'evento già importato viene aggiornato.

## Fonti attive

| Fonte | Come viene letta |
|---|---|
| valseriana.eu (Promoserio) | API REST WordPress |
| Clusone, Darfo Boario Terme, Costa Volpino | API Municipium |
| Rovetta | pagine web (MyCity) |
| Lovere | pagine web di lovereeventi.it |
| Songavazzo | pagine web (eventi e news) |

Le fonti sono in [`config/sources.yaml`](config/sources.yaml): per aggiungere un comune si aggiunge un blocco lì.

## Come funziona l'aggiornamento

A ogni modifica su `main`, GitHub Actions esegue i test e costruisce l'immagine Docker
(amd64 + arm64, quindi va bene anche sul Raspberry di Home Assistant) su
`ghcr.io/<utente>/mep-eventi:latest`. Portainer scarica quell'immagine: niente build sul Raspberry.

## Installazione su Portainer

1. **Primo push su GitHub**: dopo il primo push, in *Actions* deve comparire il job "build" verde.
   Poi in GitHub → il tuo profilo → *Packages* → `mep-eventi` → *Package settings* → **Change visibility → Public**
   (oppure aggiungi ghcr.io come registry in Portainer con un token `read:packages`).
2. **Password applicazione WordPress**: in WordPress vai su *Utenti → Profilo → Password applicazione*, crea una password chiamata "MEP Eventi" e copiala. L'utente deve poter creare eventi e caricare media (Editor o Amministratore).
3. In Portainer: **Stacks → Add stack → Repository**.
   - Repository URL: l'URL di questo repo (se è privato attiva *Authentication* con un token GitHub)
   - Reference: `refs/heads/main`
   - Compose path: `docker-compose.yml`
4. In **Environment variables** inserisci almeno:
   - `IMAGE` = `ghcr.io/<tuo-utente-github-minuscolo>/mep-eventi:latest`
   - `WP_USER`, `WP_APP_PASSWORD`
   - `LLM_PROVIDER` (`anthropic` o `openai`) e la relativa chiave `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
   - facoltativi: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `RUN_AT`, `PUBLISH_STATUS`
   (l'elenco completo con i valori di default è in [`.env.example`](.env.example))
5. **Deploy the stack**. Al primo avvio fa subito un giro, poi ogni giorno all'orario `RUN_AT`.

**Aggiornamenti**: quando il codice cambia su GitHub, aspetta che il job "build" sia verde, poi in Portainer apri lo stack e premi
**Pull and redeploy** con *Re-pull image and redeploy* attivo. Lo stato (eventi già importati) resta nel volume `mep_eventi_data`.

Senza GitHub Actions puoi costruire in locale con `docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build`.

## Comandi utili

Dalla console del container (Portainer → Containers → mep-eventi → Console):

```bash
python -m app.main --dry-run --source clusone --limit 3   # prova: non scrive nulla, stampa cosa farebbe
python -m app.main --once                                 # un giro completo adesso
python -m app.main --once --source lovere                 # solo una fonte
```

## Impostazioni principali

| Variabile | Default | Cosa fa |
|---|---|---|
| `PUBLISH_STATUS` | `draft` | `draft` bozza, `pending` in revisione, `publish` pubblica subito |
| `RUN_AT` | `05:30` | orari di esecuzione, es. `05:30,17:30` |
| `HORIZON_DAYS` | `120` | ignora (per ora) gli eventi più lontani di N giorni |
| `SKIP_RECURRING` | `true` | salta corsi settimanali, mercati fissi e simili |
| `MAX_OCCURRENCES` | `8` | per eventi con più date, quante creare al massimo |
| `MAX_PERIOD_DAYS` | `120` | mostre/rassegne più lunghe di così vengono saltate |
| `MAX_NEW_PER_RUN` | `40` | limite di nuovi eventi per giro (controllo costi) |
| `ANTHROPIC_MODEL` / `OPENAI_MODEL` | `claude-sonnet-5-5` / `gpt-4.1-mini` | modello IA |
| `LLM_VISION` | `true` | l'IA legge anche la locandina (utile quando le info sono solo lì) |
| `EVENT_CATEGORIES` | vedi `app/config.py` | categorie del calendario, separate da virgola |
| `ADD_SOURCE_LINK` | `true` | aggiunge "Fonte: …" in fondo alla descrizione |

## Problemi comuni

- **401 "rest_not_logged_in" con la password giusta**: alcuni hosting (Apache/CGI) tolgono l'header di autenticazione. Aggiungi in cima al `.htaccess` di WordPress:
  ```
  SetEnvIf Authorization "(.*)" HTTP_AUTHORIZATION=$1
  ```
- **Un sito fonte risponde 403**: alcuni siti bloccano i bot; si può cambiare `USER_AGENT` o alzare `REQUEST_DELAY`.
- **Un comune rifà il sito**: si sistema `link_pattern` in `config/sources.yaml`.

## Sviluppo

```bash
pip install -r requirements.txt pytest
pytest -q
```
