import type { ReactNode } from 'react';
import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="grid gap-1.5 text-sm text-muted-foreground">
      {label}
      {children}
    </label>
  );
}
export function Panel({
  title,
  detail,
  children,
}: {
  title: string;
  detail?: string;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {detail && <CardDescription>{detail}</CardDescription>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}
export function Stat({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="mt-2 font-mono text-2xl tracking-tight">{value}</div>
      {detail && (
        <div className="mt-1 text-xs text-muted-foreground">{detail}</div>
      )}
    </div>
  );
}
export function Status({ value }: { value: string }) {
  return (
    <Badge
      variant="outline"
      className={
        value === 'pass' || value === 'completed'
          ? 'text-blue-300'
          : value === 'blocked' || value === 'failed'
            ? 'text-red-300'
            : 'text-amber-200'
      }
    >
      {value.replaceAll('_', ' ')}
    </Badge>
  );
}
export function DataTable<T>({
  rows,
  columns,
}: {
  rows: T[];
  columns: { label: string; value: (row: T) => ReactNode }[];
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {columns.map((column, i) => (
            <TableHead key={i}>{column.label}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, i) => (
          <TableRow key={i}>
            {columns.map((column, j) => (
              <TableCell className="tabular-nums" key={j}>
                {column.value(row)}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
