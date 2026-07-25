/**
 * @fileoverview Flags useCallback / useMemo when the resulting variable
 * is only ever used as a prop on an intrinsic (lowercase) DOM element.
 *
 * Intrinsic elements (div, span, button, input, etc.) receive props as
 * DOM properties that React sets imperatively — they never compare by
 * reference, so the referential stability guarantee from useCallback /
 * useMemo is wasted. The wrapper is pure cognitive overhead.
 *
 * Rule name: `mitems/no-unnecessary-hook-to-dom`
 *
 * Example of code this rule flags:
 *
 *   const handleClick = useCallback(() => { ... }, []);     // bad
 *   return <button onClick={handleClick}>Click</button>;
 *
 * Example of code this rule does NOT flag:
 *
 *   const handleClick = useCallback(() => { ... }, []);     // ok
 *   return <MyComponent onClick={handleClick} />;           // custom component
 *
 *   const value = useMemo(() => compute(x), [x]);           // ok
 *   useEffect(() => run(value), [value]);                   // hook dependency
 */

/** @import { Rule, Scope } from "eslint" */

/** @type {Rule.RuleModule} */
export default {
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow useCallback/useMemo when the result is only passed to intrinsic DOM elements",
      recommended: false,
    },
    messages: {
      unnecessaryToDom:
        "use{{hook}} is unnecessary when the result is only passed to intrinsic DOM elements, which never compare by reference",
    },
  },

  create(context) {
    const sourceCode = context.sourceCode;

    /**
     * Map from tracked variable name to its declarator node, hook name,
     * and a reference to the scope Variable (populated at definition time).
     * @type {Map<string, { declarator: import("estree").VariableDeclarator, hookName: string, variable: Scope.Variable | null }>}
     */
    const tracked = new Map();

    return {
      VariableDeclarator(node) {
        // Must be a call expression assigned to a simple identifier
        if (
          !node.init ||
          node.init.type !== "CallExpression" ||
          node.id.type !== "Identifier"
        ) {
          return;
        }

        const callee = node.init.callee;
        if (
          callee.type !== "Identifier" ||
          (callee.name !== "useCallback" && callee.name !== "useMemo")
        ) {
          return;
        }

        // Grab the variable directly from the scope we are in at definition
        // time. This is critical — variables defined inside function
        // components live in the function scope, NOT the global scope.
        // In ESLint 10, use sourceCode.getScope(node) — context.getScope
        // was removed.
        const defScope = sourceCode.getScope(node);
        const variable = defScope.set.get(node.id.name) ?? null;

        tracked.set(node.id.name, {
          declarator: node,
          hookName: callee.name,
          variable,
        });
      },

      "Program:exit"() {
        if (tracked.size === 0) return;

        for (const [, info] of tracked) {
          const { variable } = info;
          if (!variable) continue;

          // Collect read-only references (exclude the definition write).
          const readRefs = variable.references.filter((r) => r.isRead());

          if (readRefs.length === 0) continue;

          // Check every read reference — if any is NOT on an intrinsic DOM
          // element, the hook provides value and should not be flagged.
          const allOnDom = readRefs.every((ref) =>
            isReferenceOnIntrinsicDom(ref),
          );

          if (allOnDom) {
            context.report({
              node: info.declarator,
              messageId: "unnecessaryToDom",
              data: { hook: info.hookName.replace("use", "") },
            });
          }
        }
      },
    };
  },
};

/**
 * Check whether a variable reference is used as a JSX attribute value
 * or JSX expression child on an intrinsic (lowercase-tag) DOM element.
 *
 * Walks the parent chain upward from the referenced identifier to find
 * a JSXExpressionContainer whose grandparent is either a JSXAttribute
 * on a lowercase element, or a JSXElement with a lowercase opening tag.
 *
 * @param {Scope.Reference} ref
 * @returns {boolean}
 */
function isReferenceOnIntrinsicDom(ref) {
  let node = ref.identifier;

  while (node) {
    // Check if immediate parent is a JSXExpressionContainer
    if (node.parent && node.parent.type === "JSXExpressionContainer") {
      const container = node.parent;
      const grandparent = container.parent;

      // Case 1: Attribute value — <button onClick={handleClick}>
      if (grandparent && grandparent.type === "JSXAttribute") {
        const openingEl = grandparent.parent;
        if (
          openingEl &&
          (openingEl.type === "JSXOpeningElement" ||
            openingEl.type === "JSXFragment")
        ) {
          const tagName = openingEl.name;
          if (
            tagName &&
            tagName.type === "JSXIdentifier" &&
            /^[a-z]/.test(tagName.name)
          ) {
            return true;
          }
        }
      }

      // Case 2: Expression child — <div>{value}</div>
      if (
        grandparent &&
        (grandparent.type === "JSXElement" ||
          grandparent.type === "JSXFragment")
      ) {
        // For JSXElement, check the openingElement's tag name
        const openEl =
          grandparent.type === "JSXElement"
            ? grandparent.openingElement
            : null;
        if (
          openEl &&
          openEl.name &&
          openEl.name.type === "JSXIdentifier" &&
          /^[a-z]/.test(openEl.name.name)
        ) {
          return true;
        }
      }
    }

    node = node.parent;
  }

  return false;
}
