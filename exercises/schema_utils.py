import re
import sqlite3

# Mots-clés de contraintes à ignorer quand on essaie de deviner un nom de colonne
# depuis une ligne (ex: "PRIMARY KEY (id, nom)" n'est pas une colonne).
_SKIP_KEYWORDS = {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}

_CREATE_TABLE_RE = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["\']?(\w+)["\']?\s*\(',
    re.IGNORECASE,
)


def _parse_inline_comments(sql_setup):
    """Analyse le texte de sql_setup pour extraire des commentaires SQL ('-- texte')
    associés aux tables et, si le CREATE TABLE est écrit une colonne par ligne, à
    chaque colonne. Purement optionnel : si tu n'écris aucun commentaire, le schéma
    s'affiche quand même (juste sans description).

    Convention :
        CREATE TABLE etudiants (        -- commentaire de table (optionnel)
            id INTEGER PRIMARY KEY,     -- commentaire de colonne (optionnel)
            nom TEXT
        );

    Renvoie : {nom_table: {"comment": str, "columns": {nom_colonne: str}}}
    """
    comments = {}
    current_table = None
    depth = 0

    for raw_line in sql_setup.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        comment_text = ""
        code_part = line
        if "--" in line:
            code_part, _, comment_part = line.partition("--")
            comment_text = comment_part.strip()
            code_part = code_part.strip()

        m = _CREATE_TABLE_RE.search(raw_line)
        if m and depth == 0:
            current_table = m.group(1)
            comments[current_table] = {"comment": comment_text, "columns": {}}
            depth += code_part.count("(") - code_part.count(")")
            continue

        if current_table and depth > 0:
            depth += code_part.count("(") - code_part.count(")")
            col_match = re.match(r'["\']?(\w+)["\']?', code_part)
            if col_match and comment_text:
                col_name = col_match.group(1)
                if col_name.upper() not in _SKIP_KEYWORDS:
                    comments[current_table]["columns"][col_name] = comment_text
            if depth <= 0:
                current_table = None

    return comments


def summarize_sql_setup(sql_setup, sample_rows=3):
    """Exécute sql_setup dans une base SQLite en mémoire et renvoie un résumé structuré
    du schéma (tables, colonnes, commentaires optionnels, extrait court des données),
    prêt à afficher aux étudiants.

    Renvoie None si sql_setup est vide, ou {"error": "..."} si l'exécution échoue
    (ex: faute de frappe dans le SQL) — pratique pour repérer une erreur de config
    d'exercice sans planter la page.
    """
    if not sql_setup or not sql_setup.strip():
        return None

    comments = _parse_inline_comments(sql_setup)

    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(sql_setup)
    except Exception as e:
        conn.close()
        return {"error": f"Erreur dans le sql_setup : {e}"}

    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    table_names = [row[0] for row in cur.fetchall()]

    tables = []
    for table_name in table_names:
        table_comments = comments.get(table_name, {})

        cur.execute(f"PRAGMA table_info('{table_name}')")
        columns = []
        for _cid, col_name, col_type, _notnull, _default, pk in cur.fetchall():
            columns.append({
                "name": col_name,
                "type": col_type or "",
                "pk": bool(pk),
                "comment": table_comments.get("columns", {}).get(col_name, ""),
            })

        cur.execute(f"SELECT COUNT(*) FROM '{table_name}'")
        total_rows = cur.fetchone()[0]
        cur.execute(f"SELECT * FROM '{table_name}' LIMIT {int(sample_rows)}")
        sample = [list(row) for row in cur.fetchall()]

        tables.append({
            "name": table_name,
            "comment": table_comments.get("comment", ""),
            "columns": columns,
            "sample_rows": sample,
            "total_rows": total_rows,
            "truncated": total_rows > len(sample),
        })

    conn.close()
    return {"tables": tables}
