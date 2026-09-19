# Kubernetes deployment

The Kubernetes bundle deploys the ResilienceLab control plane, not the
simulated services. It expects externally managed PostgreSQL, Redis, and a
`ReadWriteMany` persistent volume for artifact sharing between the API and
worker pods.

1. Build and publish the image, then replace `resiliencelab:0.1.0` in the API,
   worker, and migration manifests with its immutable image reference.
2. Provision PostgreSQL and Redis, enabling TLS and authentication as required
   by the target environment.
3. Copy `secret.example.yaml` outside the repository, replace every placeholder
   with a real secret, and apply it before the bundle. Do not commit that copy.
4. Ensure the cluster has a storage class that supports `ReadWriteMany`, or
   adapt `persistentvolumeclaim.yaml` to the platform's shared artifact store.
5. Apply the migration job and wait for it to complete, then apply the
   Kustomize bundle:

   ```bash
   kubectl apply -f migration-job.yaml
   kubectl wait --for=condition=complete job/resiliencelab-migrate --timeout=5m
   kubectl apply -k .
   ```

`secret.example.yaml` is intentionally not included in `kustomization.yaml`.
