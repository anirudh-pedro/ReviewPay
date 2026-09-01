import { Construction, LayoutDashboard } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Card, EmptyState, buttonClassName } from '@/components/ui';

export function PlaceholderPage({ title, description }: { title: string; description: string }) {
  return (
    <Card className="surface-grid overflow-hidden">
      <EmptyState
        action={
          <Link className={buttonClassName('secondary', 'sm')} to="/command-center">
            <LayoutDashboard aria-hidden="true" className="size-3.5" />
            Back to Command Center
          </Link>
        }
        description={description}
        icon={Construction}
        title={`${title} is next in the build queue`}
      />
    </Card>
  );
}
