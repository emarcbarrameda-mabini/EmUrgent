# i-Sumbong

## Barangay Bulletin
The Barangay Bulletin feature lets barangay admins publish official announcements, advisories, and service updates that only approved community users from the same barangay can see.

Key capabilities:
- Categorized bulletin posts with priority levels
- Pinning and expiration dates
- Attachment uploads
- Urgent bulletin email notifications
- Seen count tracking

## Run
- Apply migrations: `python manage.py migrate`
- Run server: `python manage.py runserver`
- Run tests: `python manage.py test`

## Google Maps
The report form and report detail maps use the Google Maps JavaScript API and Geocoding API. Enable both APIs and billing in Google Cloud Console, then create a browser key restricted to those APIs and your local/production HTTP referrers.

Set the key in PowerShell before starting Django:

```powershell
$env:GOOGLE_MAPS_API_KEY = "YOUR_RESTRICTED_KEY"
python manage.py runserver
```

The key is sent to the browser, so HTTP referrer and API restrictions are required. Do not commit a real key. Without a key, maps stay disabled and the report location can still be entered manually.
