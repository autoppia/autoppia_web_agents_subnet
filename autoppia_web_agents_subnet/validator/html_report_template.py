def render_html_report(fwd_summary, fwd_table_data, table_global_data, table_cwu_data, host, now):
    # fwd_summary es un dict (totales resumidos)
    # fwd_table_data = (headers, rows)
    # table_global_data = (headers, rows)
    # table_cwu_data = (headers, rows)

    def render_html_table(headers, rows, title=""):
        if not rows:
            return f"<p><b>{title}:</b> (sin datos)</p>"
        table_html = f"<h2>{title}</h2><table>"
        table_html += "<thead><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead>"
        table_html += "<tbody>"
        for r in rows:
            table_html += "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
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
    .summary-block {{
      background: #fff8e1;
      border: 1px solid #ffe082;
      padding: 15px;
      margin-bottom: 25px;
      font-family: monospace;
    }}
  </style>
</head>
<body>
  <h1>📊 Autoppia Web Agents – Reporte</h1>
  <p><b>Fecha:</b> {now} <br><b>Host:</b> {host}</p>

  <h2>Resumen Global</h2>
  <div class="summary-block"><pre>{fwd_summary}</pre></div>

  {render_html_table(*fwd_table_data, title="Forward Totals")}
  {render_html_table(*table_global_data, title="Coldkey Global")}
  {render_html_table(*table_cwu_data, title="Coldkey / Web / Use-case")}

</body>
</html>"""
