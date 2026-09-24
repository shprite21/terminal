'use client';

import { useEffect, useRef } from 'react';
import { flushSync } from 'react-dom';
import { parsePortfolio, type PortfolioDraft } from './portfolio';

type Tool = {
  name: string;
  description: string;
  inputSchema: object;
  annotations: { readOnlyHint: boolean; untrustedContentHint: boolean };
  execute: (input: unknown) => unknown;
};
type Context = {
  registerTool: (
    tool: Tool,
    options: { signal: AbortSignal },
  ) => void | Promise<void>;
};
type Actions = {
  configure: (portfolio: PortfolioDraft) => void;
  analyze: () => Promise<unknown>;
  read: () => unknown;
};

export function usePortfolioTools(actions: Actions) {
  const current = useRef(actions);
  useEffect(() => {
    current.current = actions;
  });
  useEffect(() => {
    const context = (document as Document & { modelContext?: Context })
      .modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const tools: Tool[] = [
      {
        name: 'configure_portfolio',
        description:
          'Replace the visible portfolio draft with a validated long-only allocation. Does not save, analyze, or trade.',
        annotations: { readOnlyHint: false, untrustedContentHint: false },
        inputSchema: {
          type: 'object',
          additionalProperties: false,
          properties: {
            name: { type: 'string', minLength: 1, maxLength: 60 },
            holdings: {
              type: 'array',
              minItems: 1,
              maxItems: 30,
              items: {
                type: 'object',
                properties: {
                  ticker: { type: 'string' },
                  weight: { type: 'number', exclusiveMinimum: 0, maximum: 100 },
                },
                required: ['ticker', 'weight'],
                additionalProperties: false,
              },
            },
            source: { type: 'string', enum: ['yahoo','massive','synthetic'] },
            period: { type: 'string', enum: ['6mo', '1y', '2y', '5y'] },
            benchmark: { type: 'string' },
            initial_capital: { type: 'number', minimum: 1, maximum: 1e9 },
            risk_free_rate: { type: 'number', minimum: 0, maximum: 25 },
          },
          required: [
            'name',
            'holdings',
            'period',
            'benchmark',
            'initial_capital',
            'risk_free_rate',
          ],
        },
        execute(input) {
          const portfolio = parsePortfolio(input);
          flushSync(() => current.current.configure(portfolio));
          return { status: 'configured', portfolio };
        },
      },
      {
        name: 'analyze_portfolio',
        description:
          'Load the selected provider history and complete the visible portfolio analysis. No order placement.',
        inputSchema: {
          type: 'object',
          properties: {},
          additionalProperties: false,
        },
        annotations: { readOnlyHint: false, untrustedContentHint: true },
        async execute() {
          return await current.current.analyze();
        },
      },
      {
        name: 'read_portfolio_workspace',
        description:
          'Read the current portfolio draft, loading state and analysis summary.',
        inputSchema: {
          type: 'object',
          properties: {},
          additionalProperties: false,
        },
        annotations: { readOnlyHint: true, untrustedContentHint: true },
        execute() {
          return current.current.read();
        },
      },
    ];
    for (const tool of tools) {
      try {
        void Promise.resolve(
          context.registerTool(tool, { signal: lifecycle.signal }),
        ).catch((error) =>
          console.warn('Portfolio tool registration failed', error),
        );
      } catch (error) {
        console.warn('Portfolio tool registration failed', error);
      }
    }
    return () => lifecycle.abort();
  }, []);
}
