# Global Grid OS Mission

GlobalGrid2050 is not just a website and not just a dashboard.

The mission is to build an open-source grid intelligence operating system that anyone can clone, verify, adapt and run independently.

The operating system must not depend on one company account, one hosted bucket, one dashboard, one cloud provider, one AI assistant, or one maintainer.

It must travel as a reproducible bundle: data, source registers, pipelines, audit reports, definitions, documentation and user interfaces that can be rebuilt from first principles.

## What Global Grid OS Means

Global Grid OS means a public, forkable and verifiable foundation for electricity-system intelligence.

A developer in another country should be able to clone the project, replace the GB data sources with their own national grid sources, run the same pipeline discipline, and build a local grid intelligence system without asking permission.

A researcher should be able to inspect the source data pathway, read the definitions, rerun the processing scripts, and understand why the published output is trusted.

A small business should be able to use the public tools without paying for expensive consultant reports before they even understand the market.

A public-interest user should be able to see how the data was produced and challenge it if necessary.

## The Core Principle

The OS lives in the cloneable, verifiable, regenerable bundle.

It does not live in any one server.

It does not live in any one dashboard.

It does not live in any one storage bucket.

It does not live in any one AI conversation.

The hosted website is one public instance of the OS. It is not the OS itself.

## Open Source First

The project should be useful even if the original hosted version disappears.

That means the code, data pipeline, definitions and audit trail must be available in open repositories.

The preferred architecture is not dependency on a central bucket controlled by Ventus.

The preferred architecture is a self-contained open system that others can fork, audit and rebuild.

## Git as the Distribution Layer

Git is not merely a code repository in this architecture.

Git is the distribution layer for the open operating system.

It carries the scripts, documentation, audit files, data contracts and compact working data.

Cloning the repository should give another builder enough structure to understand and reproduce the system.

Git is suitable while the dataset remains modest and compact. If the dataset eventually becomes too large for Git, the project can add release snapshots and external archives while keeping the reproducible recipe in Git.

## Data Repo, UI Repo and Homepage Repo

GlobalGrid2050 should separate responsibilities.

The data repo is the source layer. It stores compact data, pipelines, source registers, audit reports and data-quality doctrine.

The UI repo is the reader layer. It should consume the published data and show it clearly, without carrying raw data or silently changing the data.

The homepage repo is the catalogue layer. It points people to the tools, datasets, documentation and mission.

This separation prevents the old monolith problem where app code, raw data, scripts, documentation and experiments all lived in one place.

## Data Doctrine

The data must be reproducible, not merely uploaded.

A static zip is an assertion.

A pipeline that can be rerun and audited is evidence.

The repo should prefer pipeline evidence over trust in one-off files.

The repo should record the source, the method, the key, the schema, the checks, the failures and the fixes.

The repo should treat every painful bug as training data.

## Invariants, Not Snapshots

A good pipeline asserts data laws, not temporary snapshots.

A settled historical canary can be a strict invariant.

A uniqueness rule can be a strict invariant.

A schema contract can be a strict invariant.

A duplicate-key count must be zero.

But file counts, row counts and total megabytes are living quantities. They can grow. They should be floors, bands or monitoring signals, not permanent equality checks.

## Write, Audit, Publish

The mature pattern is Write-Audit-Publish.

Write the new data to a staging area.

Audit the staged data.

Publish only if the audit passes.

Bad staged data should be discarded before it reaches the trusted published tree.

This is the difference between a script that writes files and a data product that can be defended.

## Optional Serving Layers

Cloudflare R2, object storage, CDNs and APIs can be useful for a high-traffic hosted dashboard.

They are not the mission-critical foundation of the open OS.

They are convenience layers for a public instance.

They must not become the only place where the real data lives.

A fork of the project should not need Ventus infrastructure to function.

## Preservation and Releases

The project should eventually publish citable releases.

Zenodo or an equivalent preservation archive can provide durable, citable snapshots independent of a single GitHub repo or company account.

A good release should include code, data, audit reports, source register, definitions and checksums.

The aim is not only to make the project visible today.

The aim is to make it recoverable and understandable in the future.

## AI Operating Model

AI can help build the OS, but AI must not be the source of truth.

AI can audit, patch, test and document.

The repository must hold the durable record.

The working model is separation of duties.

One assistant can audit.

One assistant can patch.

One assistant can test.

The human owner decides.

No assistant should mark its own homework without evidence.

## What This Project Is Not

It is not a private SaaS dashboard pretending to be open.

It is not a collection of screenshots.

It is not a static data dump.

It is not a consultancy report locked inside a PDF.

It is not dependent on one cloud bucket.

It is not a monolith where everything is mixed together until nobody can reason about it.

## What Success Looks Like

Success means another competent person can clone the work, understand the data model, rerun the pipeline, inspect the audit report, reproduce the output and adapt the system to another grid.

Success means a public dashboard can exist, but the dashboard is not the only form of the project.

Success means the project is useful to Ventus, but not trapped inside Ventus.

Success means the data can be questioned and defended.

Success means the system becomes easier to fork, not harder, as it matures.

## Roadmap Discipline

First, prove the data repo.

Clean the data.

Remove duplicate keys.

Make the backfill reproducible.

Make the monthly updater idempotent.

Write the audit trail.

Then build the UI repo as a reader of the data repo.

Then connect the homepage repo as the catalogue and gateway.

Then create citable releases.

Only then consider optional speed layers such as R2 for the hosted instance.

Do not let serving convenience replace open-source independence.

## One Sentence Mission

GlobalGrid2050 exists to become a cloneable, verifiable and regenerable open-source grid intelligence operating system, so that electricity-system knowledge can be built, audited and adapted by anyone, not locked inside one company, one dashboard, one server or one report.
