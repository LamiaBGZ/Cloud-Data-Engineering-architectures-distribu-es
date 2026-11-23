# Ingestion relationnelle Bronze sur Databricks Free Edition

L’export local utilise Python 3 et sa bibliothèque standard. Dans Databricks, utiliser un notebook Python serverless et un volume géré Unity Catalog. Le rôle d’ingestion a besoin de `USE CATALOG`, `USE SCHEMA` et `READ VOLUME` sur la source, ainsi que de `WRITE VOLUME` pour le téléversement. Dans le catalogue cible, prévoir `CREATE SCHEMA` si `bronze` reste à créer, puis `USE SCHEMA`, `CREATE TABLE`, `SELECT` et `MODIFY` selon les tables existantes. Réserver l’accès au volume et aux tables Bronze aux rôles habilités à lire les données personnelles.

## Exécution

1. Depuis la racine du projet, générer les cinq CSV dans un nouveau dossier local. Le script ouvre `source_relationnelle/voltanord.sqlite` en lecture seule et vérifie son intégrité.

   ```powershell
   python src/export_relationnel_sqlite.py export_relationnel_2026
   ```

2. Dans Catalog Explorer, téléverser les cinq CSV dans un même sous-dossier du volume, par exemple `/Volumes/<catalogue>/<schema>/raw/relationnel/lot_initial`. Garder ce chemin pour les rejeux. Conserver aussi une copie brute du SQLite et des deux dumps SQL dans un dossier d’archives distinct du volume. Traiter les originaux et les exports comme des fichiers sensibles.
3. Importer `notebooks/01_bronze/01_ingestion_relationnelle.py` comme notebook source Databricks. Renseigner `target_catalog` avec le catalogue cible et `source_directory` avec le chemin complet du dossier des CSV. Exécuter toutes les cellules avec un seul chargement à la fois.
4. Vérifier les nombres affichés pour `customers` (456), `sites` (502), `meters` (512), `contracts` (443) et `tariffs` (6). Relancer avec les mêmes paramètres pour obtenir cinq messages « rejeu vérifié ». Un rejeu identique conserve les écritures et leurs horodatages. Un contenu ou chemin source différent pour un snapshot déjà chargé provoque un arrêt. Après un échec partiel, relancer avec les mêmes fichiers pour compléter les tables restantes. Chaque écriture Delta est atomique à l’échelle de sa table.

## Schéma et périmètre du lot

Les volumes et en-têtes correspondent à la base livrée. Les colonnes métier sont conservées en texte en Bronze, y compris les identifiants, codes postaux et valeurs atypiques. L’export utilise un marqueur réservé pour distinguer les valeurs SQL `NULL` des chaînes vides. Le notebook vérifie les en-têtes, la largeur des lignes, les volumes et le contenu relu dans Delta. Il affiche les nombres de clés vides et de doublons sans filtrer les lignes ni afficher leurs valeurs.

`snapshot_date` vaut `2026-01-01` pour `contracts` et `2026-04-30` pour les autres tables. `ingestion_timestamp` correspond à l’instant UTC du chargement et `source_file` au chemin complet du CSV. Le notebook s’arrête à Bronze. Les événements CDC restent dans leur source et aucune table Gold n’est publiée.
