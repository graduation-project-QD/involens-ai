AGENTS.md

Purpose

This file defines the mandatory working rules for Codex when analyzing, predicting, and implementing changes in this repository.

1. Mandatory Clarification Before Coding

Before writing or modifying any code:

Review the request and identify every unclear, missing, conflicting, or uncertain requirement.

Ask the user about all unclear points.

Do not make assumptions.

Do not invent missing business rules, technical requirements, field values, validation rules, API behavior, database behavior, or error-handling behavior.

Do not start implementation until the user has answered the required questions.

When information is insufficient to complete the task, stop and ask for clarification.

2. Analysis and Approval Workflow

Codex must follow this workflow for every implementation request.

Step 1: Analyze the problem

Before coding, provide an analysis that includes:

The problem to be solved.

The expected behavior.

The relevant actors or components.

The affected modules, classes, APIs, database tables, or external integrations.

Known constraints.

Missing or uncertain information.

Step 2: Identify use cases

Describe the applicable use cases, including:

Main success flow.

Alternative flows.

Validation cases.

Error or failure cases.

External integration behavior, when applicable.

Do not invent use cases that are not supported by the user's request. Ask the user when a use case is unclear.

Step 3: Propose an implementation approach

Before making changes, present:

The proposed solution.

The implementation flow.

The files expected to be modified.

Any new files that may be required.

Important design decisions.

Potential risks or dependencies.

Step 4: Wait for explicit approval

Do not write, modify, delete, or generate code until the user explicitly accepts the proposed approach.

Silence, partial answers, or answers to clarification questions do not automatically count as approval.

Step 5: Implement only the approved scope

After approval:

Implement only the accepted solution.

Do not expand the scope.

Do not add unrelated improvements.

Do not refactor unrelated code.

Do not introduce new architecture, libraries, dependencies, configuration, or behavior without approval.

If a new uncertainty appears during implementation, stop and ask the user before continuing.

3. File Creation Rules

Do not create any file that was not explicitly requested or included in the approved implementation plan.

Before creating an additional file, ask the user for approval.

Do not rename, move, or delete existing files without explicit approval.

4. No Arbitrary Implementation

Do not add behavior merely because it is common, recommended, or convenient.

When any of these are needed but not defined, ask the user first.

5. Clean Code Requirements

All implemented code must follow clean-code principles.

Mandatory requirements:

Use clear and meaningful names.

Keep functions focused on one responsibility.

Avoid duplicated logic.

Avoid unnecessary complexity.

Avoid deeply nested conditions when a clearer structure is possible.

Keep business logic separate from transport, persistence, and infrastructure concerns where the existing architecture supports that separation.

Follow the repository's existing conventions and architecture.

Do not introduce a new coding style that conflicts with the current project.

Handle errors explicitly according to approved requirements.

Do not leave unused code, imports, variables, or commented-out code.

Do not hardcode business values ​​unless the user explicitly approves them.

6. Function Comment Requirements

Every function or method must have a comment that explains its business responsibility.

The comment must describe:

What business operations the function performs.

The meaning of important inputs, when necessary.

The expected result.

Important side effects or external calls, when applicable.

Comments must explain the purpose of the function, not repeat the code line by line.

Example:

/** 
* Calculates the insurance premium for the selected vehicle configuration 
* by validating the input and requesting the current premium from the provider. 
*/
public InsurancePrice calculatePrice(PriceRequ

7. Logging Requirements

Every function or method must include logs that make its execution and business purpose observable.

At minimum, add logs where applicable for:

Function start.

Important business decisions.


Successful completion.

Validation failures.

Exceptions or failed operations.

Avoid meaningless, excessive, or duplicated logs.

Example:

/**
 * Creates an insurance order after the request has been validated.
 */
public OrderResult createOrder(CreateOrderRequest request) {
    log.info("Starting insurance order creation. transactionId={}", request.getTransactionId());

    try {
        OrderResult result = orderService.create(request);
        log.info("Insurance order created successfully. transactionId={}", request.getTransactionId());
        return result;
    } catch (Exception exception) {
        log.error(
            "Insurance order creation failed. transactionId={}",
            request.getTransactionId(),
            exception
        );
        throw exception;
    }
}

8. Existing Project Conventions

Before proposing implementation:

Inspect the relevant existing code.

Identify the current architecture, naming conventions, error-handling approach, logging framework, package structure, and coding style.

Reuse existing patterns when they are suitable.

Report any conflict between the request and the existing project structure.

Ask the user before introducing a different pattern.

9. Scope Changes During Implementation

When implementation reveals that the approved plan is incomplete or cannot be completed as described:

Stop implementation.

Explain the discovered issue.

Describe the required change.

List any additional files or code changes needed.

Wait for explicit approval before continuing.




