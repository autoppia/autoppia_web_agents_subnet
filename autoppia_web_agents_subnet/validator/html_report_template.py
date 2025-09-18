def render_html_report(fwd_table_data, table_global_data, table_cwu_data, task_table_data, task_summary_data, host, now):
    # Paleta de colores suaves (se repite si hay más proyectos que colores)
    COLOR_PALETTE = [
        "#e3f2fd",  # light blue
        "#f1f8e9",  # light green
        "#fff3e0",  # light orange
        "#fce4ec",  # light pink
        "#ede7f6",  # light purple
        "#e0f7fa",  # light cyan
        "#f9fbe7",  # light lime
        "#fbe9e7",  # light coral
        "#f3e5f5",  # light violet
        "#e8f5e9",  # light mint
        "#edeff0",  # light gray
        "#fffde7",  # light yellow
    ]

    project_color_map = {}

    def get_project_color(project: str) -> str:
        """Assign a consistent color for each project automatically."""
        if project not in project_color_map:
            idx = len(project_color_map) % len(COLOR_PALETTE)
            project_color_map[project] = COLOR_PALETTE[idx]
        return project_color_map[project]

    def render_html_table(headers, rows, title=""):
        if not rows:
            return f"<p><b>{title}:</b> (no data)</p>"

        # Sort Coldkey Global by Hotk (column 1) descending
        if title == "Coldkey Global":
            try:
                rows = sorted(rows, key=lambda r: int(r[1]), reverse=True)
            except Exception:
                pass

        table_html = f"<h2>{title}</h2><table>"
        table_html += "<thead><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead>"
        table_html += "<tbody>"

        for r in rows:
            row_html = ""
            bg_style = ""

            # Detect indices
            web_idx = headers.index("Web") if "Web" in headers else None
            coldkey_idx = headers.index("Coldkey") if "Coldkey" in headers else None
            hotk_idx = headers.index("Hotk") if "Hotk" in headers else None

            # Background color by Web project
            if web_idx is not None:
                try:
                    web_val = str(r[web_idx])
                    if web_val:
                        bg_style = f"background-color:{get_project_color(web_val.lower())};"
                except Exception:
                    pass

            for i, cell in enumerate(r):
                txt = str(cell)
                style = bg_style

                # Italic for Coldkey column
                if coldkey_idx is not None and i == coldkey_idx:
                    txt = f"<i>{txt}</i>"

                # Bold for Web column
                if web_idx is not None and i == web_idx:
                    txt = f"<b>{txt}</b>"

                # Bold for Hotk column
                if hotk_idx is not None and i == hotk_idx:
                    txt = f"<b>{txt}</b>"

                # Color percentages
                if "%" in txt:
                    try:
                        clean_txt = txt.replace("%", "").replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
                        val = float(clean_txt)
                        if val <= 25:
                            style += "color:#b71c1c;font-weight:bold;"  # red
                        elif val <= 50:
                            style += "color:#e65100;font-weight:bold;"  # orange
                        elif val <= 75:
                            style += "color:#f9a825;font-weight:bold;"  # amber
                        else:
                            style += "color:#1b5e20;font-weight:bold;"  # green
                    except Exception:
                        pass

                row_html += f"<td style='{style}'>{txt}</td>"
            table_html += f"<tr>{row_html}</tr>"

        table_html += "</tbody></table>"
        return table_html

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{
      font-family: Arial, sans-serif;
      font-size: 14px;
      color: #333;
      background-color: #f8f9fa;
      margin: 0;
      padding: 20px;
    }}
    h1 {{
      color: #4a148c;
      text-align: center;
    }}
    h2 {{
      color: #6a1b9a;
      margin-top: 30px;
      border-bottom: 2px solid #ccc;
      padding-bottom: 4px;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      margin-bottom: 25px;
    }}
    th, td {{
      border: 1px solid #ddd;
      padding: 8px;
      text-align: center;
    }}
    th {{
      background-color: #6a1b9a;
      color: white;
    }}
    tr:nth-child(even) td {{
      background-color: #f2f2f2;
    }}
  </style>
</head>
<body>
  <h1>📊 Autoppia Web Agents – Report {now}</h1>

  {render_html_table(*fwd_table_data, title="Forward Totals")}
  {render_html_table(*task_table_data, title="Last Forward Tasks")}
  {render_html_table(*task_summary_data, title="Global Task Summary")}
  {render_html_table(*table_global_data, title="Coldkey Global")}
  {render_html_table(*table_cwu_data, title="Coldkey / Web / Use-case")}
</body>
</html>"""
