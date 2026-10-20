# Deployment verification

After every push, verify deployment over SSH on the home server:

```bash
ssh -i ~/.ssh/id_rsa titus@ssh.mastitus.my.id
cd ~/code/gold-digger
```

Confirm the deployed commit matches the pushed commit, inspect `docker compose ps` and relevant service logs, and check the affected local API and public page. A healthy web container alone does not verify data ingestion or forecasting. Report any verification failure explicitly.

# Local Docker test cleanup

After every local Docker build/test, remove the images, containers, volumes and build cache created specifically for that test, including on failure. Use a dedicated build tag/builder and track test resources so cleanup does not remove unrelated images, caches or user data. Verify cleanup before finishing. Avoid a local Docker build when ordinary Python tests provide the needed validation.
