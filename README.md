# Projet fil rouge — VoltaNord Énergie

*Cloud Data Engineering & architectures distribuées — MSc Data, 2e année*

## Le contexte

VoltaNord Énergie est un fournisseur d'électricité (fictif) d'environ 450 clients, particuliers et professionnels, répartis dans 12 régions de France métropolitaine. Son SI est un empilement classique : une base opérationnelle, une plateforme de télérelève des compteurs communicants, un outil de facturation, un export bancaire, un CRM ancien et des données météo achetées à l'extérieur.

La direction vous confie la construction de sa **plateforme lakehouse sur Azure**. Elle veut, d'ici fin janvier :

1. suivre la consommation par région, par jour et par segment de clientèle, et mesurer sa sensibilité à la température ;
2. réconcilier ce qui a été facturé avec ce qui a été réellement consommé ;
3. suivre le recouvrement (impayés, prélèvements rejetés) ;
4. repérer les compteurs au comportement anormal ;
5. connaître l'état exact de n'importe quel contrat à n'importe quelle date ;
6. gouverner tout cela : droits d'accès, données personnelles, lignage.

La période couverte va du **1er janvier au 30 avril 2026**.

> **Avertissement.** Comme en entreprise, ces sources ne sont ni propres ni parfaitement documentées. Détecter, mesurer et traiter les problèmes de qualité fait partie du travail et de la note. Tenez un **registre qualité** (voir plus bas) dès la première séance.

## Arborescence

```
voltanord_data/
├── source_relationnelle/        base opérationnelle (à charger dans une base SQL)
│   ├── voltanord_postgres.sql   PostgreSQL / Azure Database for PostgreSQL
│   ├── voltanord_azuresql.sql   Azure SQL Database / SQL Server
│   └── voltanord.sqlite         même contenu, pour explorer en local
├── landing/                     fichiers bruts déposés par les systèmes sources
│   ├── telemetrie/              relevés horaires des compteurs (JSON Lines gzip)
│   ├── cdc_contrats/            flux de changements de la table contracts (JSON Lines)
│   ├── factures/                exports mensuels de l'outil de facturation (JSON)
│   ├── paiements/               exports bancaires mensuels (CSV)
│   ├── meteo/                   données météo quotidiennes (CSV)
│   └── crm_tickets/             exports du CRM (XML)
└── reference/                   petits référentiels propres
    ├── ref_stations_meteo.csv
    └── ref_departements_regions.csv
```

## Les sources

### 1. Base opérationnelle (relationnel)

Cinq tables : `customers`, `sites`, `meters`, `contracts`, `tariffs`. La première étape consiste à la **déployer dans une base SQL Azure**, puis à l'ingérer comme une vraie source (connecteur JDBC, Lakehouse Federation ou pipeline de copie).

- Un client possède un ou plusieurs **sites** (lieux de consommation). Un site possède un ou plusieurs **compteurs** au fil du temps. Un contrat lie un client à un site.
- `meter_id` est le PRM du compteur : un identifiant de **14 caractères**.
- `tariffs` est historisée : chaque tarif a une période de validité (`valid_from`, `valid_to` inclus).
- **Date d'extraction** : clients, sites, compteurs et tarifs sont extraits au 30/04/2026. **Les contrats sont extraits au 01/01/2026** ; toutes les évolutions ultérieures arrivent par le flux CDC.

### 2. Télémétrie des compteurs (`landing/telemetrie/`)

Un relevé par compteur et par heure, déposé chaque jour par deux concentrateurs (`HE-NORD`, `HE-SUD`), rangé par **date d'ingestion** : `ingest_date=AAAA-MM-JJ/HE-XXX_AAAAMMJJ.jsonl.gz`.

Extrait de la documentation de l'éditeur (version 1 du firmware) :

| Champ | Description |
|---|---|
| `meterId` | Identifiant du compteur |
| `ts` | Horodatage du relevé |
| `index_kwh` | Index cumulé du compteur, en kWh |
| `power_w` | Puissance moyenne sur l'heure, en W |
| `status` | `OK` ou `ERR` |

Un nouveau firmware est en cours de déploiement sur le parc depuis février. Sa documentation ne vous a pas été transmise.

La consommation d'une heure se déduit de la **différence entre deux index successifs** d'un même compteur.

### 3. Flux CDC des contrats (`landing/cdc_contrats/`)

Journal des changements capturés sur la table `contracts` (format de type Debezium), un fichier par jour. Chaque ligne contient `op` (`c` création, `u` mise à jour, `d` suppression), `ts_ms`, `source.lsn` (ordre de validation en base), ainsi que l'état `before` et `after` de la ligne. Les dates sont encodées comme dans Debezium.

### 4. Factures (`landing/factures/`)

Un fichier JSON par mois de consommation, contenant un tableau de factures avec des lignes imbriquées (`lines`). Règles de facturation :

- facture mensuelle, sur la période du contrat incluse dans le mois ;
- l'**option tarifaire et la puissance appliquées sont celles en vigueur en fin de mois** ;
- le prix du kWh est celui de la table `tariffs` valable au premier jour du mois facturé ;
- heures creuses : de **22 h à 6 h, heure légale française** ; heures pleines le reste du temps ;
- abonnement : `kVA × prix_kva_mois × jours facturés / jours du mois` ;
- contribution : 0,03 € par kWh ; TVA : 20 % sur le total HT.

### 5. Paiements (`landing/paiements/`)

Un CSV par mois d'opération bancaire : `reference`, `facture`, `date_operation`, `montant`, `moyen` (`PRLV`, `CB`, `VIR`, `CHQ`), `statut` (`OK`, `REJETE`), `libelle`.

### 6. Météo (`landing/meteo/`)

Données quotidiennes par station, un fichier par mois : précipitations (`RR`, mm), températures minimale, maximale et moyenne (`TN`, `TX`, `TM`, °C), vent moyen (`FFM`, m/s). Une station de référence par région (`reference/ref_stations_meteo.csv`).

### 7. Tickets CRM (`landing/crm_tickets/`)

Exports XML des demandes clients : catégorie, canal, dates, texte libre saisi par le conseiller, historique des évènements.

## Ce que vous devez livrer

| Séance | Jalon | Contenu |
|---|---|---|
| S1 | `v0.1` | Environnement prêt, base SQL déployée, schéma d'architecture cible |
| S2 | `v0.2` | Couche bronze : toutes les sources ingérées **sans perte** (y compris les lignes rejetées) |
| S3 | `v0.3` | Silver : télémétrie normalisée et dédoublonnée, contrats historisés (SCD2) |
| S4 | ADR | Delta Lake vs Apache Iceberg, avec mesures à l'appui |
| S5 | `v0.4` | DAG Airflow d'ingestion incrémentale, rejouable sur n'importe quelle date |
| S6 | `v0.5` | Gold, règles de qualité bloquantes, déploiement CI/CD |
| S7-S8 | — | Modèle de droits Unity Catalog, données personnelles protégées, glossaire Purview |
| S9 | `v1.0` | Tableau de bord et estimation du coût mensuel de la plateforme |
| S10 | — | Soutenance |

### Tables gold attendues (minimum)

- `conso_region_jour` : kWh par région et par jour local, avec la température moyenne du jour ;
- `thermosensibilite` : kWh supplémentaires par degré de froid, par type de chauffage et par segment ;
- `reconciliation_facturation` : pour chaque facture, kWh facturés vs kWh mesurés et prix appliqué vs prix attendu ;
- `recouvrement` : montant dû, payé et restant dû par facture et par client ;
- `anomalies_compteurs` : compteurs suspects, avec type d'anomalie et date de début ;
- `contrats_historique` : une ligne par version de contrat avec `valid_from` / `valid_to`.

### Le registre qualité

Un fichier `QUALITE.md` dans votre repo. Pour chaque problème trouvé : la source concernée, le symptôme, le nombre de lignes touchées, la règle appliquée (corriger, rejeter, mettre en quarantaine) et l'endroit du code où c'est fait. **Chaque problème documenté et correctement traité rapporte des points.**

## Règles du jeu

- Ne modifiez jamais les fichiers de `landing/` : tout traitement doit être rejouable depuis les fichiers bruts.
- Aucune donnée personnelle (nom, email, téléphone, IBAN, date de naissance) ne doit être lisible en clair par le groupe « analystes ».
- Tout chiffre présenté en soutenance doit pouvoir être recalculé par votre pipeline.
- Chaque membre de l'équipe est propriétaire d'au moins un composant, indiqué dans le README.
