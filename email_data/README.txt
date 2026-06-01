# email_data/
Drop your test email files here (PDF or Excel .xlsx / .xls).
Files uploaded through the HTML dashboard are also saved here automatically.

Supported formats:
  .pdf   – one or more emails per document
  .xlsx  – one email per row (columns: From, To, Subject, Date, Body)

Run from CLI:
  python main.py --data-dir email_data
  python main.py --data-dir email_data --log-level DEBUG
