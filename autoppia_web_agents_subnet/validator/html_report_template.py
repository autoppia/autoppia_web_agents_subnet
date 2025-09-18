def render_html_report(fwd_summary, fwd_table, table_global, table_cwu, host, now):
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
      border-bottom: 2px solid #ccc;
      padding-bottom: 4px;
      margin-top: 30px;
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
    tr:nth-child(even) {{
      background-color: #f2f2f2;
    }}
    .summary-block {{
      background: #fff8e1;
      border: 1px solid #ffe082;
      padding: 15px;
      margin-bottom: 25px;
      font-family: monospace;
    }}
    pre {{
      white-space: pre-wrap;
      word-wrap: break-word;
    }}
  </style>
</head>
<body>
  <h1>📊 Autoppia Web Agents – Reporte</h1>
  <p><b>Fecha:</b> {now} <br><b>Host:</b> {host}</p>

  <h2>Resumen Global</h2>
  <div class="summary-block">
    <pre>{fwd_summary}</pre>
  </div>

  <h2>Forward Totals</h2>
  <pre>{fwd_table}</pre>

  <h2>Coldkey Global</h2>
  <pre>{table_global}</pre>

  <h2>Coldkey / Web / Use-case</h2>
  <pre>{table_cwu}</pre>

</body>
</html>"""
