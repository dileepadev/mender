# Commit Message Guidelines

A good commit message should be descriptive and provide context about the changes made. This helps improve code review, debugging, and long-term maintainability.

Table of Contents:

- [Commit Message Guidelines](#commit-message-guidelines)
  - [Commit Message Format](#commit-message-format)
    - [`<type>`](#type)
    - [`<scope>`](#scope)
    - [`<short message>`](#short-message)
    - [`<optional issue references>`](#optional-issue-references)
    - [`<optional PR reference>`](#optional-pr-reference)
    - [`<optional longer description>`](#optional-longer-description)
  - [Issue and PR References](#issue-and-pr-references)
    - [Best Practices](#best-practices)
    - [Examples for Issue and PR References](#examples-for-issue-and-pr-references)
    - [Summary Table for Issue and PR Linking (with Scope)](#summary-table-for-issue-and-pr-linking-with-scope)
  - [✅ Summary Examples with All Fields](#-summary-examples-with-all-fields)

## Commit Message Format

Use the following format for commit messages:

```md
<type>(<scope>): <short message> (<optional issue references>) (<optional PR reference>)

<optional longer description>
```

### `<type>`

The `<type>` field indicates the nature of the changes made in the commit. Use one of the following values:

| Type     | Description                                                   |
|----------|---------------------------------------------------------------|
| feat     | A new feature or enhancement to existing functionality.       |
| fix      | A bug fix or correction of an issue.                          |
| docs     | Documentation updates (e.g., README, code comments).          |
| style    | Code style changes (e.g., formatting, indentation, no logic). |
| refactor | Code refactoring without changing external behavior.          |
| perf     | Performance improvements.                                     |
| test     | Adding or modifying tests.                                    |
| chore    | Routine tasks, maintenance, or tooling changes.               |

### `<scope>`

The `<scope>` is optional, but recommended. It helps clarify which part of the project the commit affects. For example:

| Scope         | Description                                           |
|---------------|-------------------------------------------------------|
| repo          | Project-wide configuration or setup                   |
| config        | Build scripts, environment, or settings               |
| auth          | Authentication logic or features                      |
| api           | API endpoints or integrations                         |
| ui            | User interface components or styling                  |
| db            | Database models or queries                            |

### `<short message>`

A concise summary of what the commit does.

Writing Tips:

- Use the imperative mood (e.g., “Add” not “Added”)
- Capitalize the first letter
- Don’t end with a period
- Keep under 50 characters if possible
- Be specific (e.g., “Add agent tools” > “Update code”)
- Avoid "I", "this commit", or "fix" as vague verbs

### `<optional issue references>`

Optionally link the commit to relevant issues using GitHub keywords such as `fixes`, `closes`, `resolves`, or `refs`. Multiple issues can be referenced by separating them with commas.

### `<optional PR reference>`

Optionally link the commit to a pull request using the format `(#<number>)`. This should be placed at the end of the commit message.

### `<optional longer description>`

An optional detailed description of the changes made in the commit. This can include the reasoning behind the changes, implementation details, or any other relevant information. Separate this section from the header with a blank line.

## Issue and PR References

Use GitHub keywords to link commits to issues, and standard notation for PRs.

### Best Practices

- **Pull Requests**: Use `(#<number>)` at the very end of the header. This is automatically recognized by GitHub.
  - ✅ `(#5)`
  - 🚫 `(pr #5)` or `refs #5` for the PR itself.
- **Issues**: Use standard GitHub keywords (`fixes`, `refs`, `closes`, `resolves`) in parentheses before the PR number.

### Examples for Issue and PR References

**Straightforward PR reference:**

```md
chore(repo): Migrate v1.1.0 codebase to new repository (#5)
```

**Issue + PR:**

```md
fix(auth): Prevent session expiration bug (fixes #42) (#102)
```

**Multiple Issues + PR:**

```md
chore(repo): Migrate v1.1.0 codebase to new repository (refs #1, #2) (#5)
```

### Summary Table for Issue and PR Linking (with Scope)

| Purpose                | Example Commit Message                                              | Result                             |
| ---------------------- | ------------------------------------------------------------------- | ---------------------------------- |
| Close single issue     | `fix(ui): Resolve button alignment issue (fixes #12) (#100)`        | Closes #12, links PR #100          |
| Reference single issue | `docs(config): Clarify setup instructions (refs #34) (#105)`        | Links issue #34, PR #105           |
| Reference PR Only      | `chore(deps): Bump version (#45)`                                   | Links PR #45                       |
| Close multiple issues  | `feat(api): Add registration (fixes #56, #57) (#200)`               | Closes #56, #57, links PR #200     |
| Mixed References       | `fix(api): Handle edge case (fixes #12, refs #23) (#150)`           | Closes #12, refs #23, links PR #150|
| Multiple PRs (rare)    | `chore(repo): Sync repos (#5, #6)`                                  | Links PR #5 and #6                 |

## ✅ Summary Examples with All Fields

```md
feat(api): Add login endpoint (fixes #12) (#101)

This adds a new login endpoint to the API that allows users to authenticate using their email and password.
```

```md
fix(auth): Prevent session expiration bug (fixes #42) (#102)
```

```md
chore(repo): Migrate v1.1.0 codebase to new repository (refs #1, #2) (#5)
```

```md
chore(deps): Bump version (#45)
```
