# Deployment verification

After every push, verify deployment over SSH on the home server:

```bash
ssh -i ~/.ssh/id_rsa titus@ssh.mastitus.my.id
cd ~/code/gold-digger
```

Confirm the deployed commit matches the pushed commit, inspect `docker compose ps` and relevant service logs, and check the affected local API and public page. A healthy web container alone does not verify data ingestion or forecasting. Report any verification failure explicitly.
