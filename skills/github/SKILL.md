---
name: github
description: Interact with GitHub repositories (issues, PRs, commits, releases).
metadata:
  requires:
    bins: [gh]
---

# GitHub Skill

You can interact with GitHub using the `gh` CLI tool.

## Common Operations

### Issues
```bash
gh issue list                          # List open issues
gh issue create --title "..." --body "..."  # Create an issue
gh issue view 123                      # View issue details
gh issue close 123                     # Close an issue
```

### Pull Requests
```bash
gh pr list                             # List open PRs
gh pr create --title "..." --body "..."     # Create PR
gh pr view 123                         # View PR details
gh pr merge 123                        # Merge PR
gh pr checkout 123                     # Checkout PR locally
```

### Repository
```bash
gh repo view                           # View current repo
gh repo clone owner/repo               # Clone repository
gh release list                        # List releases
gh release create v1.0.0               # Create release
```

### Search
```bash
gh search repos "query"                # Search repositories
gh search issues "query"               # Search issues
gh search prs "query"                  # Search pull requests
```

## Tips
- Always run `gh auth status` first to verify authentication
- Use `--json` flag for structured output: `gh issue list --json number,title,state`
- Use `--jq` for filtering: `gh pr list --json number,title --jq '.[].title'`
