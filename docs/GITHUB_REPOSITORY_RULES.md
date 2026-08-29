# Required GitHub Repository Rules & Branch Protection

## Branch Protection Rules for `main`

The `main` branch MUST enforce the following protection rules:

1. **Require Pull Request Reviews**: Minimum 1 approving review required before merging.
2. **Require Status Checks to Pass**:
   - `Test & Validate` (`ci.yml`)
   - `Build & Security Scan` (`container.yml`)
   - `CodeQL` (`codeql.yml`)
3. **Require Linear History**: Prevent merge commits if rebase/squash merge is configured.
4. **Do Not Allow Force Pushes**: Force pushing to `main` is strictly prohibited.
5. **Do Not Allow Deletion**: Branch deletion of `main` is strictly prohibited.
