import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import NewProposal from '../components/NewProposal';
import { api } from '../api';

vi.mock('../api', () => ({
  api: { createProposal: vi.fn(), getOrders: vi.fn() },
}));

const customers = [
  { id: 1, first_name: 'Alice', last_name: 'Johnson', email: 'alice@example.com', segment: 'regular', total_spent: 18000 },
  { id: 2, first_name: 'Bob', last_name: 'Smith', email: 'bob@example.com', segment: 'new', total_spent: 999 },
];

function setup() {
  const onCreated = vi.fn();
  const user = userEvent.setup();
  render(<NewProposal customers={customers} onClose={() => {}} onCreated={onCreated} />);
  return { user, onCreated, submit: screen.getByRole('button', { name: /add to inbox/i }) };
}

beforeEach(() => {
  api.createProposal.mockReset();
  api.getOrders.mockReset().mockResolvedValue([
    { id: 9, woo_order_id: 1042, status: 'failed', total: 2499 },
  ]);
});

describe('NewProposal', () => {
  it('keeps Add disabled until the email has a customer, subject and body', async () => {
    const { user, submit } = setup();
    expect(submit).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Customer'), '2');
    await user.type(screen.getByLabelText('Subject'), 'Thanks!');
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText('Message'), 'Hi Bob');
    expect(submit).toBeEnabled();
  });

  it('sends an email proposal with the typed subject and body', async () => {
    api.createProposal.mockResolvedValue({ id: 77, title: 'Email for Bob' });
    const { user, submit, onCreated } = setup();
    await user.selectOptions(screen.getByLabelText('Customer'), '2');
    await user.type(screen.getByLabelText('Subject'), 'Thanks!');
    await user.type(screen.getByLabelText('Message'), 'Hi Bob');
    await user.click(submit);
    expect(api.createProposal).toHaveBeenCalledWith({
      proposal_type: 'follow_up_email', customer_id: 2, note: null, subject: 'Thanks!', body: 'Hi Bob',
    });
    expect(onCreated).toHaveBeenCalledWith({ id: 77, title: 'Email for Bob' });
  });

  it("won't offer the customer's current segment", async () => {
    const { user } = setup();
    await user.click(screen.getByRole('button', { name: 'Segment change' }));
    await user.selectOptions(screen.getByLabelText('Customer'), '1');
    const regular = screen.getByRole('option', { name: 'Regular' });
    expect(regular).toBeDisabled();
  });

  it("lists the customer's orders for an order issue", async () => {
    api.createProposal.mockResolvedValue({ id: 5, title: 'x' });
    const { user, submit } = setup();
    await user.click(screen.getByRole('button', { name: 'Order issue' }));
    await user.selectOptions(screen.getByLabelText('Customer'), '1');
    expect(api.getOrders).toHaveBeenCalledWith('1');
    await user.selectOptions(await screen.findByLabelText('Order'), '1042');
    await user.click(submit);
    expect(api.createProposal).toHaveBeenCalledWith(expect.objectContaining({
      proposal_type: 'issue_alert', woo_order_id: 1042, issue_type: 'payment_failed',
    }));
  });

  it('shows the server error instead of closing', async () => {
    api.createProposal.mockRejectedValue(new Error('Bob Smith is already vip.'));
    const { user, submit, onCreated } = setup();
    await user.selectOptions(screen.getByLabelText('Customer'), '2');
    await user.type(screen.getByLabelText('Subject'), 'a');
    await user.type(screen.getByLabelText('Message'), 'b');
    await user.click(submit);
    expect(await screen.findByText('Bob Smith is already vip.')).toBeInTheDocument();
    expect(onCreated).not.toHaveBeenCalled();
  });
});
