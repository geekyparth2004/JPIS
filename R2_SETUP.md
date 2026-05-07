# R2 Setup

This project is configured to use Cloudflare R2 for public media files.

## Bucket

- Bucket name: `jpis-media`
- Public development URL: `https://pub-bd63e1d2b92646408ec795bcec957944.r2.dev`

## Environment variables

Add these to your local `.env` file:

```env
R2_ACCOUNT_ID=your_cloudflare_account_id
R2_BUCKET_NAME=jpis-media
R2_ACCESS_KEY_ID=your_r2_access_key_id
R2_SECRET_ACCESS_KEY=your_r2_secret_access_key
R2_ENDPOINT_URL=https://your_cloudflare_account_id.r2.cloudflarestorage.com
R2_PUBLIC_BASE_URL=https://pub-bd63e1d2b92646408ec795bcec957944.r2.dev
```

## Upload assets

Upload the local `assets/` folder:

```powershell
python scripts/r2_upload.py assets
```

Upload a specific file:

```powershell
python scripts/r2_upload.py "brochure.pdf" --prefix uploads
```

The script preserves folder structure, so `assets/chairman.jpg` becomes:

`https://pub-bd63e1d2b92646408ec795bcec957944.r2.dev/assets/chairman.jpg`

## Production note

The current `r2.dev` URL is fine for setup and testing. For production, connect a custom domain such as `media.yourdomain.com` to this bucket in Cloudflare so your asset URLs are stable and not rate-limited.
