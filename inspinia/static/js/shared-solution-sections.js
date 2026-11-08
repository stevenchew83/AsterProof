(() => {
    for (const paper of document.querySelectorAll(".public-shared-paper")) {
        const title = paper.querySelector(":scope > header > h1, :scope > header > h2");
        const problem = paper.querySelector(":scope > .public-shared-problem");
        const blocks = paper.querySelector(":scope > .public-shared-blocks");
        if (!title || !problem || !blocks) continue;

        const problemHeading = problem.querySelector(":scope > h2, :scope > h3");
        const topic = problem.querySelector(":scope > .public-shared-tags");
        if (!problemHeading || !topic) continue;

        const reference = problemHeading.textContent.trim();
        topic.textContent = [
            reference === title.textContent.trim() ? "" : reference,
            topic.textContent.trim(),
        ].filter(Boolean).join(" · ");
        topic.hidden = !topic.textContent;
        problemHeading.textContent = "Problem statement";

        const solution = document.createElement("section");
        solution.className = "public-shared-solution";
        const heading = document.createElement(problemHeading.localName);
        heading.id = paper.id ? `${paper.id}-solution` : "shared-solution-heading";
        heading.textContent = "Solution";
        solution.setAttribute("aria-labelledby", heading.id);
        solution.append(heading);

        const summary = paper.querySelector(":scope > .public-shared-summary");
        (summary || blocks).before(solution);
        if (summary) solution.append(summary);
        solution.append(blocks);

        const stepTag = problemHeading.localName === "h3" ? "h4" : "h3";
        for (const step of blocks.querySelectorAll(":scope > .public-shared-block > h2, :scope > .public-shared-block > h3")) {
            const stepHeading = document.createElement(stepTag);
            stepHeading.append(...step.childNodes);
            step.replaceWith(stepHeading);
        }
    }
})();
