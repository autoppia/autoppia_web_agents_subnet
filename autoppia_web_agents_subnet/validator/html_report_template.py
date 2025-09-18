def render_html_report(fwd_table_data, table_global_data, table_cwu_data, host, now):
    def render_html_table(headers, rows, title=""):
        if not rows:
            return f"<p><b>{title}:</b> (sin datos)</p>"

        # Orden especial: si es Coldkey Global → ordenar por Hotk desc (col=1)
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
            for i, c in enumerate(r):
                cell = str(c)
                style = ""

                # Detectar si la columna es un porcentaje
                if "%" in cell:
                    try:
                        val = float(cell.replace("%", ""))
                        if val <= 25:
                            style = "color: #b71c1c; font-weight:bold;"  # rojo
                        elif val <= 50:
                            style = "color: #e65100; font-weight:bold;"  # naranja
                        elif val <= 75:
                            style = "color: #f9a825; font-weight:bold;"  # amarillo/ámbar
                        else:
                            style = "color: #1b5e20; font-weight:bold;"  # verde
                    except Exception:
                        pass

                row_html += f"<td style='{style}'>{cell}</td>"
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
  <h1>📊 Autoppia Web Agents – Reporte</h1>
  <p><b>Fecha:</b> {now} <br><b>Host:</b> {host}</p>

  {render_html_table(*fwd_table_data, title="Forward Totals")}
  {render_html_table(*table_global_data, title="Coldkey Global")}
  {render_html_table(*table_cwu_data, title="Coldkey / Web / Use-case")}

</body>
</html>"""
