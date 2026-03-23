import type { PropsWithChildren, ReactNode } from "react";

interface PanelProps extends PropsWithChildren {
  title: string;
  extra?: ReactNode;
}

export function Panel(props: PanelProps) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{props.title}</h2>
        {props.extra}
      </div>
      <div>{props.children}</div>
    </section>
  );
}
