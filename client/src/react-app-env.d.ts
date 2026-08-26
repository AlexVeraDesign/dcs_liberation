/// <reference types="react-scripts" />
/// <reference types="@testing-library/jest-dom" />

declare namespace jest {
  interface Matchers<R> {
    toContainHTML(html: string): R;
    toBeEmptyDOMElement(): R;
    toHaveTextContent(text: string | RegExp): R;
  }
}
